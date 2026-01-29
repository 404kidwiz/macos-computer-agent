"""Minimal local-only agent server (placeholder)."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class Handler(BaseHTTPRequestHandler):
    def _send(self, code=200, payload=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if payload is None:
            payload = {}
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not_found"})


def main():
    server = HTTPServer(("127.0.0.1", 8765), Handler)
    print("macOS agent running on http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
