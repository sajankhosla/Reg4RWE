#!/usr/bin/env python3
"""Print recent Reg4RWE appraisal use.

Local lines come from data/usage.jsonl. Hosted lines come from the private
blob store when BLOB_READ_WRITE_TOKEN is set. Pull it with:

    vercel env pull .env.local --yes --project reg4rwe
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
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


def _print_events(title: str, events: list[dict]) -> None:
    print(title)
    if not events:
        print("  none")
        return
    for event in events:
        precedents = "; ".join(event.get("precedents") or []) or "none"
        design = (event.get("design") or "").replace("\n", " ")
        if len(design) > 140:
            design = design[:137] + "..."
        print(f"  {event.get('at')}  {event.get('source')}  {event.get('outcome')}")
        print(f"    design: {design}")
        print(f"    precedents: {precedents}")


if __name__ == "__main__":
    _load_env()
    from usage_log import read_local, read_remote

    _print_events("On this machine", read_local())
    print()
    try:
        remote = read_remote()
    except Exception as error:
        remote = []
        print(f"Hosted log could not be read ({error}).")
    else:
        if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
            print("Hosted log: set BLOB_READ_WRITE_TOKEN, or run vercel env pull .env.local --yes --project reg4rwe")
        else:
            _print_events("Hosted log", remote)
