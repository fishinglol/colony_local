"""A tiny MCP server for tests, no dependencies: two tools, over stdio or over HTTP.

  python fake_mcp.py [log-file]     the stdio transport (newline-delimited JSON-RPC); every request is appended to the log
  FakeHttpMcp()                     the streamable-HTTP transport on a free port; `.seen` records (headers, message) per POST
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = [
    {"name": "echo", "description": "Send text back unchanged.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "delete_everything", "description": "A dangerous action for approval tests.",
     "inputSchema": {"type": "object", "properties": {"what": {"type": "string"}}}},
]


def answer(msg: dict) -> dict | None:
    """The JSON-RPC reply to `msg`, or None for a notification."""
    method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if msg_id is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fake", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": f"{params.get('name')} ran with {json.dumps(params.get('arguments') or {})}"}]}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


class FakeHttpMcp(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.seen: list[tuple[dict, dict]] = []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/mcp"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(({k.lower(): v for k, v in self.headers.items()}, msg))
        body = answer(msg)
        if body is None:
            self.send_response(202)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):        # no server-initiated stream
        self.send_response(405)
        self.end_headers()

    def do_DELETE(self):
        self.send_response(200)
        self.end_headers()


def main() -> None:
    log = open(sys.argv[1], "a") if len(sys.argv) > 1 else None
    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        if log:
            log.write(json.dumps(msg) + "\n")
            log.flush()
        body = answer(msg)
        if body is not None:
            sys.stdout.write(json.dumps(body) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
