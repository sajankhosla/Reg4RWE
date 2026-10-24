#!/usr/bin/env python3
"""stdio MCP server for Reg4RWE.

Clients that speak the Model Context Protocol can call appraise_rwe_design.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from appraise_core import appraise

PROTOCOL = "2024-11-05"
SERVER = {"name": "reg4rwe", "version": "1.0.0"}

TOOLS = [
    {
        "name": "appraise_rwe_design",
        "description": (
            "Critically appraise a proposed real-world evidence study against public "
            "FDA and EMA feedback. Returns the closest precedents, the regulator's "
            "own words, and the feedback that recurs across those precedents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "design": {
                    "type": "string",
                    "description": (
                        "The study or design to appraise: question, population, "
                        "data source, comparator, and the decision the evidence is meant to support."
                    ),
                }
            },
            "required": ["design"],
            "additionalProperties": False,
        },
    }
]


def respond(message_id, result):
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def fail(message_id, code, message):
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def handle(message):
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}
    if method == "initialize":
        requested = (params.get("protocolVersion") or PROTOCOL)
        version = requested if requested.startswith("202") else PROTOCOL
        return respond(message_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER,
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return respond(message_id, {})
    if method == "tools/list":
        return respond(message_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "appraise_rwe_design":
            return fail(message_id, -32602, f"Unknown tool {name}")
        design = arguments.get("design") or ""
        text = appraise(str(design))
        return respond(message_id, {"content": [{"type": "text", "text": text}], "isError": False})
    if message_id is None:
        return None
    return fail(message_id, -32601, f"Method not found: {method}")


def read_message():
    stream = sys.stdin.buffer
    first = stream.read(1)
    if not first:
        return None
    if first == b"{":
        rest = stream.readline()
        return json.loads(first + rest)
    header = first
    while b"\r\n\r\n" not in header and len(header) < 8192:
        chunk = stream.read(1)
        if not chunk:
            return None
        header += chunk
    length = 0
    for line in header.decode("ascii", "replace").splitlines():
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    body = stream.read(length) if length else b""
    return json.loads(body.decode("utf-8"))


def write_message(payload):
    if payload is None:
        return
    raw = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main():
    while True:
        try:
            message = read_message()
        except json.JSONDecodeError:
            continue
        if message is None:
            break
        write_message(handle(message))


if __name__ == "__main__":
    main()
