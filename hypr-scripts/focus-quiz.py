#!/usr/bin/env python3
"""Focus Mode exit quiz (v1): open questions about the session topic."""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

STATE_FILE = Path.home() / ".config" / "focus-mode" / "state.json"


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def ask_lmstudio(prompt):
    try:
        req = urllib.request.Request(
            "http://localhost:1234/v1/chat/completions",
            data=json.dumps({"model": "local-model",
                             "messages": [{"role": "user", "content": prompt}],
                             "temperature": 0.7,
                             "max_tokens": 300}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read().decode())
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def main():
    state = load_state()
    if not state.get("active"):
        print("No active Focus Mode session.")
        return 0
    topic = (state.get("topic") or "").strip() or "this session"
    print(f"Topic: {topic}\n")
    qs = (ask_lmstudio(
        f"Write 3 short study questions about '{topic}', one per line.") or "").splitlines()
    qs = [q.strip() for q in qs if q.strip()][:3]
    if not qs:
        print("No AI backend — answer honestly, then unlock manually.")
        return 1
    for q in qs:
        print("Q:", q)
        input("A: ")
    print("\nDone. Unlocking.")
    subprocess.run(["focus-mode", "unlock"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
