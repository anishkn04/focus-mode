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


def api_root(base: str) -> str:
    return base.replace("/v1", "/api/v1").rstrip("/")


def lmstudio_inventory(base: str, timeout: int = 10):
    """Return (loaded_key, downloadable_key). v1 first, then v0."""
    try:
        req = urllib.request.Request(api_root(base) + "/models")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        dl = None
        for m in data.get("models", []):
            if str(m.get("type", "")).lower() == "embedding":
                continue
            key = m.get("key", "") or m.get("id", "")
            if not key:
                continue
            dl = dl or key
            if m.get("loaded_instances"):
                return key, key
        return None, dl
    except Exception:
        return None, None


def lmstudio_load(base: str, key: str, timeout: int = 300) -> bool:
    """Load via POST /api/v1/models/load; verify serving afterwards."""
    loaded, _ = lmstudio_inventory(base)
    if loaded:
        return True
    try:
        req = urllib.request.Request(
            api_root(base) + "/models/load",
            data=json.dumps({"model": key}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except Exception as e:
        print(f"(load failed: {e})")
        return False
    import time
    deadline = time.time() + 120
    while time.time() < deadline:
        loaded, _ = lmstudio_inventory(base)
        if loaded:
            return True
        time.sleep(5)
    return False


_LOADED_BY_US = False


def ask_lmstudio(prompt, model=None):
    global _LOADED_BY_US
    base = "http://localhost:1234/v1"
    if model is None:
        loaded, dl = lmstudio_inventory(base)
        if loaded:
            model = loaded
        elif dl:
            print(f"(loading {dl} into memory…)")
            if not lmstudio_load(base, dl):
                return None
            _LOADED_BY_US = True
            model, _ = lmstudio_inventory(base)
            model = model or dl
        else:
            return None
    try:
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps({"model": model,
                             "messages": [{"role": "user", "content": prompt}],
                             "temperature": 0.7,
                             "max_tokens": 600}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read().decode())
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def lmstudio_unload() -> None:
    """Unload only what this quiz loaded."""
    if not _LOADED_BY_US:
        return
    loaded, _ = lmstudio_inventory("http://localhost:1234/v1")
    if not loaded:
        return
    try:
        req = urllib.request.Request(
            "http://localhost:1234/api/v1/models/unload",
            data=json.dumps({"instance_id": loaded}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60):
            pass
        print(f"(unloaded {loaded} — auto-loaded for this quiz)")
    except Exception as e:
        print(f"(unload skipped: {e})")


def main():
    state = load_state()
    if not state.get("active"):
        print("No active Focus Mode session — nothing to unlock.")
        return 2
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
    lmstudio_unload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
