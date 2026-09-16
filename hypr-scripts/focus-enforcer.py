#!/usr/bin/env python3
"""Focus Mode enforcer daemon for Hyprland (v1).

Windows open at session start are grandfathered (left alone). New windows
whose class is not allowlisted are closed via hyprctl dispatch.
Stops when state.json has {"active": false} or disappears.
"""
import json
import subprocess
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "focus-mode"
STATE_FILE = CONFIG_DIR / "state.json"
PID_FILE = CONFIG_DIR / "enforcer.pid"
LOG_FILE = CONFIG_DIR / "enforcer.log"

POLL_INTERVAL = 2.0


def log(msg: str) -> None:
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%F %T')} {msg}\n")
    except OSError:
        pass


def load_state() -> dict | None:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def hypr_clients() -> list:
    try:
        out = subprocess.run(
            ["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0:
            return []
        return json.loads(out.stdout or "[]")
    except Exception:
        return []


def close_window(addr: str) -> bool:
    try:
        r = subprocess.run(
            ["hyprctl", "dispatch", "closewindow", f"address:{addr}"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def is_allowed(win: dict, state: dict) -> bool:
    allowed = {str(c).lower() for c in state.get("allowed", [])}
    cls = str(win.get("class", "") or "").lower()
    addr = str(win.get("address", ""))
    if addr in set(state.get("grandfathered", [])):
        return True
    return cls in allowed


def main() -> int:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(__import__("os").getpid()))
    log("enforcer started")
    try:
        while True:
            state = load_state()
            if not state or not state.get("active"):
                log("state inactive/missing; exiting")
                break
            for win in hypr_clients():
                addr = str(win.get("address", ""))
                if not addr or is_allowed(win, state):
                    continue
                ok = close_window(addr)
                log(f"BLOCK class={win.get('class', '?')} addr={addr} closed={ok}")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except OSError:
            pass
        log("enforcer stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
