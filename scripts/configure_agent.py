"""Write the backend URL/token into aiui-agent/lib/config.js before packaging the AIX.

    python scripts/configure_agent.py --base-url https://poc.example.com --token <API_TOKEN>
    python scripts/configure_agent.py --lang en
    python scripts/configure_agent.py --reset      # back to LOCAL DEMO mode (commit-safe)

The token ends up inside the AIX package. Use a PoC-only token, rotate it after the
test, and do not commit the filled file (CI fails if config.js is not empty).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "aiui-agent" / "lib" / "config.js"


def set_value(src: str, key: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    new, n = re.subn(rf"({key}: )'[^']*'", rf"\g<1>'{escaped}'", src)
    if n != 1:
        raise SystemExit(f"could not find {key} in {CONFIG}")
    return new


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url")
    p.add_argument("--token")
    p.add_argument("--lang", choices=["ko", "en"])
    p.add_argument("--speech-lang")
    p.add_argument("--reset", action="store_true")
    a = p.parse_args(argv)
    src = CONFIG.read_text(encoding="utf-8")
    if a.reset:
        src = set_value(set_value(src, "API_BASE_URL", ""), "API_TOKEN", "")
    if a.base_url is not None:
        if a.base_url and not a.base_url.startswith("https://"):
            print("WARNING: the glasses reach the server through the phone; use an HTTPS URL reachable from the phone.")
        src = set_value(src, "API_BASE_URL", a.base_url.rstrip("/"))
    if a.token is not None:
        src = set_value(src, "API_TOKEN", a.token)
    if a.lang:
        src = set_value(src, "UI_LANG", a.lang)
    if a.speech_lang is not None:
        src = set_value(src, "SPEECH_LANG", a.speech_lang)
    CONFIG.write_text(src, encoding="utf-8")
    print(f"Updated {CONFIG}")
    if not a.reset:
        print("Do NOT commit this file with a URL/token. Run with --reset before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
