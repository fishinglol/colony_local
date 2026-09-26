"""A pretend OpenAI-compatible model server, so Pi can be tested with no API key and no network.

It logs everything Pi sends (run/requests.jsonl) and answers by a fixed script:
  user says "WRITE <path> <text>"  -> asks Pi to call its write tool
  user says "FAIL"                 -> the server answers 429 (rate limited)
  user says "READ <path>"          -> asks Pi to call its read tool
  user says "RUN <command>"        -> asks Pi to call its bash tool
  a tool result comes back         -> says what the tool returned
  anything else                    -> says which model it is and lists every user message it can see
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = Path(__file__).parent / "run" / "requests.jsonl"


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content or [] if isinstance(part, dict))


def tool_args(tools, name, wanted):
    """Build tool-call arguments using whatever parameter names Pi's schema uses."""
    props = next((t["function"]["parameters"].get("properties", {}) for t in tools if t["function"]["name"] == name), {})
    args = {}
    for kind, value in wanted.items():
        key = next((k for k in props if kind in k), kind)
        args[key] = value
    return args


def decide(body):
    msgs, tools, model = body["messages"], body.get("tools") or [], body["model"]
    last = msgs[-1]
    if last["role"] == "tool":
        return {"text": f"[{model}] tool said: {text_of(last['content'])[:120]}"}
    said = text_of(last["content"])
    if said.startswith("WRITE "):
        _, path, *rest = said.split(" ")
        return {"tool": ("write", tool_args(tools, "write", {"path": path, "content": " ".join(rest)}))}
    if said.startswith("READ "):
        return {"tool": ("read", tool_args(tools, "read", {"path": said[5:]}))}
    if said.startswith("RUN "):
        return {"tool": ("bash", tool_args(tools, "bash", {"command": said[4:]}))}
    seen = [text_of(m["content"]) for m in msgs if m["role"] == "user"]
    assistant = [text_of(m["content"])[:60] for m in msgs if m["role"] == "assistant"]
    return {"text": f"[{model}] I see user messages: {seen} and earlier assistant replies: {assistant}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system = [text_of(m["content"]) for m in body["messages"] if m["role"] in ("system", "developer")]
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps({
                "model": body["model"],
                "system": system,
                "tools": [t["function"]["name"] for t in body.get("tools") or []],
                "messages": [{"role": m["role"], "content": text_of(m.get("content")), "tool_calls": m.get("tool_calls")}
                             for m in body["messages"] if m["role"] not in ("system", "developer")],
            }) + "\n")
        if text_of(body["messages"][-1].get("content")) == "FAIL":  # to test how errors show up
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Provider returned error (rate limited)","code":429}}')
            return
        plan = decide(body)
        chunk = lambda delta, finish=None, usage=None: {  # noqa: E731
            "id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": int(time.time()), "model": body["model"],
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **({"usage": usage} if usage else {})}
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if "tool" in plan:
            name, args = plan["tool"]
            first = {"role": "assistant", "content": None, "tool_calls": [
                {"index": 0, "id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
            chunks, finish = [chunk(first)], "tool_calls"
        else:
            chunks, finish = [chunk({"role": "assistant", "content": plan["text"]})], "stop"
        chunks.append(chunk({}, finish, usage))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
