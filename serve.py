#!/usr/bin/env python3
"""Serve the regulatory feedback navigator on http://127.0.0.1:8765."""

import json
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
CORPUS = ROOT / "data" / "corpus.json"

from appraise_core import appraise
from usage_log import log_appraisal, read_local, read_remote


def load_local_env():
    env_file = ROOT / ".env.local"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def usage_events():
    merged = {}
    try:
        remote = read_remote(100)
    except Exception:
        remote = []
    for event in read_local(100) + remote:
        merged[event.get("id") or id(event)] = event
    return sorted(merged.values(), key=lambda event: event.get("at") or "", reverse=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/usage":
            body = json.dumps({"events": usage_events()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/logs":
            self.path = "/logs.html"
        if path == "/api/corpus":
            if not CORPUS.exists():
                body = b'{"error":"Run python3 pipeline/build_corpus.py first."}'
                self.send_response(404)
            else:
                body = CORPUS.read_bytes()
                self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/appraise":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            design = payload.get("design") or payload.get("study") or ""
            text = appraise(str(design))
            log_appraisal("local", str(design), text)
            body = json.dumps({"appraisal": text}).encode("utf-8")
            status = 200
        except Exception as error:
            body = json.dumps({"error": str(error)}).encode("utf-8")
            status = 400
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith("GET /api/corpus"):
            return
        super().log_message(fmt, *args)


if __name__ == "__main__":
    load_local_env()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("Navigator at http://127.0.0.1:8765")
    server.serve_forever()
