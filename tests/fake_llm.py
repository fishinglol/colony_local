"""A pretend OpenAI-compatible model server for testing the real Pi engine with no key and no network.

It records every request (`server.requests`) and answers by a fixed script:
  the user's last line starts with "WRITE <path> <text>" -> asks Pi to call its write tool
  ... "READ <path>"                                       -> asks Pi to call its read tool
  ... "MCP <tool> <json>"                                 -> asks Pi to call the connector tool <tool> with that JSON
  ... "MCPSEARCH <text>"                                  -> asks the connector gateway to search its tools
  ... "MCPINSTALL <url>"                                  -> asks the connector gateway to install a server (must be refused)
  a tool result comes back                                -> says what the tool returned
  anything else                                           -> says which model it is
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content or [] if isinstance(part, dict))


def _args(tools, name, wanted):
    props = next((t["function"]["parameters"].get("properties", {}) for t in tools if t["function"]["name"] == name), {})
    return {next((k for k in props if kind in k), kind): value for kind, value in wanted.items()}


def _decide(body):
    msgs, tools, model = body["messages"], body.get("tools") or [], body["model"]
    last = msgs[-1]
    if last["role"] == "tool":
        return {"text": f"[{model}] tool said: {text_of(last['content'])[:120]}"}
    said = text_of(last["content"]).splitlines()[-1] if text_of(last["content"]) else ""
    if said.startswith("WRITE "):
        _, path, *rest = said.split(" ")
        return {"tool": ("write", _args(tools, "write", {"path": path, "content": " ".join(rest)}))}
    if said.startswith("MCP "):
        _, name, *rest = said.split(" ")
        return {"tool": ("mcp", {"tool": name, "args": json.loads(" ".join(rest) or "{}")})}
    if said.startswith("MCPSEARCH "):
        return {"tool": ("mcp", {"search": said[10:]})}
    if said.startswith("MCPINSTALL "):
        return {"tool": ("mcp", {"action": "install", "url": said[11:]})}
    if said.startswith("READ "):
        return {"tool": ("read", _args(tools, "read", {"path": said[5:]}))}
    return {"text": f"[{model}] hello"}


class FakeModelServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[dict] = []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append({
            "model": body["model"],
            "system": [text_of(m["content"]) for m in body["messages"] if m["role"] in ("system", "developer")],
            "tools": [t["function"]["name"] for t in body.get("tools") or []],
            "messages": [{"role": m["role"], "content": text_of(m.get("content"))} for m in body["messages"]
                         if m["role"] not in ("system", "developer")],
            "auth": self.headers.get("Authorization"),
            "reasoning": {k: body[k] for k in ("reasoning", "reasoning_effort", "enable_thinking") if k in body},
        })
        plan = _decide(body)
        chunk = lambda delta, finish=None, usage=None: {  # noqa: E731
            "id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": int(time.time()), "model": body["model"],
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **({"usage": usage} if usage else {})}
        if "tool" in plan:
            name, args = plan["tool"]
            first = {"role": "assistant", "content": None, "tool_calls": [
                {"index": 0, "id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
            chunks, finish = [chunk(first)], "tool_calls"
        else:
            chunks, finish = [chunk({"role": "assistant", "content": plan["text"]})], "stop"
        chunks.append(chunk({}, finish, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
