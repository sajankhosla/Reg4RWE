"""Private usage log for Reg4RWE appraisals."""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from usage_log import read_remote, store_incoming


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 20_000:
            self._send(413, {"error": "Usage event is too large."})
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "Send a JSON usage event."})
            return
        if not store_incoming(payload if isinstance(payload, dict) else {}):
            self._send(400, {"error": "A usage event needs a design string."})
            return
        self._send(200, {"ok": True})

    def do_GET(self):
        expected = os.environ.get("USAGE_READ_TOKEN", "").strip()
        supplied = self.headers.get("Authorization", "")
        if not expected or supplied != f"Bearer {expected}":
            self._send(404, {"error": "Not found."})
            return
        limit = 100
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        for part in query.split("&"):
            if part.startswith("limit="):
                try:
                    limit = max(1, min(200, int(part.split("=", 1)[1])))
                except ValueError:
                    limit = 100
        try:
            events = read_remote(limit)
        except Exception as error:
            self._send(500, {"error": str(error)})
            return
        self._send(200, {"store": "vercel-blob", "events": events})
