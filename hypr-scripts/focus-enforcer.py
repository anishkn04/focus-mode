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
SITE_FILE = CONFIG_DIR / "site-allowlist.json"
PID_FILE = CONFIG_DIR / "enforcer.pid"
LOG_FILE = CONFIG_DIR / "enforcer.log"

POLL_INTERVAL = 2.0
ANNOUNCED: set = set()  # addrs already notified about (notify once each)
VIOLATIONS: dict = {}  # addr -> first-seen timestamp of site violation
_SITE_CACHE: dict = {}

TRANSIENT_TITLES = {"", "untitled", "loading", "loading..."}

# Never kill these, even if not in the allowlist (shell / picker / auth).
ALWAYS_ALLOW_CLASSES = {
    "fuzzel",
    "dev.noctalia.noctalia",
    "polkit-gnome-authentication-agent-1",
    "xdg-desktop-portal-gtk",
    "hyprpicker",
}


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


def hypr_eval(lua: str) -> bool:
    """Run Lua via `hyprctl eval`. Classic `hyprctl dispatch <syntax>` is
    Lua-wrapped since Hyprland 0.56, so targeted window ops go through eval."""
    try:
        r = subprocess.run(
            ["hyprctl", "eval", lua], capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except Exception:
        return False


def active_address() -> str:
    try:
        out = subprocess.run(
            ["hyprctl", "activewindow", "-j"], capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0 or not out.stdout.strip():
            return ""
        return str(json.loads(out.stdout).get("address", "") or "")
    except Exception:
        return ""


def close_window(addr: str) -> bool:
    """Close one window by address: focus it, verify, close, restore focus."""
    prev = active_address()
    if prev == addr:
        return hypr_eval("hl.dispatch(hl.dsp.window.close())")
    if not hypr_eval(f'hl.dispatch(hl.dsp.focus({{ window = "address:{addr}" }}))'):
        return False
    time.sleep(0.3)
    if active_address() != addr:
        return False  # never close a window we did not verify as focused
    ok = hypr_eval("hl.dispatch(hl.dsp.window.close())")
    time.sleep(0.3)
    if prev and prev != addr:
        # Best-effort focus restore; ignore failure (window may be gone).
        hypr_eval(f'hl.dispatch(hl.dsp.focus({{ window = "address:{prev}" }}))')
    return ok


def is_allowed(win: dict, state: dict) -> bool:
    allowed = {str(c).lower() for c in state.get("allowed", [])}
    cls = str(win.get("class", "") or "").lower()
    init_cls = str(win.get("initialClass", "") or "").lower()
    addr = str(win.get("address", ""))
    pid = win.get("pid")

    # Grandfathered: stored as {address: {pid, class}} so a NEW window that
    # reuses a dead window's address does NOT inherit the exemption
    # (Hyprland recycles addresses). Legacy lists are still honored.
    gf = state.get("grandfathered", [])
    if isinstance(gf, dict):
        info = gf.get(addr) or {}
        if pid and info.get("pid") == pid:
            if str(info.get("class", "")).lower() in (cls, init_cls):
                return True
    elif addr in gf:
        return True
    if cls in ALWAYS_ALLOW_CLASSES or init_cls in ALWAYS_ALLOW_CLASSES:
        return True
    if cls in allowed or init_cls in allowed:
        return True
    return False


def notify(summary: str, body: str = "") -> None:
    try:
        subprocess.run(["noctalia", "msg", "notification-show", summary, body],
                       timeout=5, capture_output=True)
    except Exception:
        pass
    try:
        subprocess.run(["notify-send", "--app-name=Focus Mode", summary, body],
                       timeout=5, capture_output=True)
    except Exception:
        pass


def load_site_rules() -> dict:
    """Load site-allowlist.json, cached by mtime (live-editable, no restart)."""
    try:
        mtime = SITE_FILE.stat().st_mtime
    except OSError:
        return {}
    if _SITE_CACHE.get("mtime") == mtime:
        return _SITE_CACHE.get("rules", {})
    try:
        rules = json.loads(SITE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return _SITE_CACHE.get("rules", {})
    _SITE_CACHE["mtime"] = mtime
    _SITE_CACHE["rules"] = rules
    return rules


def is_browser(win: dict, rules: dict) -> bool:
    browsers = {str(b).lower() for b in rules.get("browsers", [])}
    if not browsers:
        return False
    return str(win.get("class", "") or "").lower() in browsers


def page_title(win: dict) -> str:
    import re
    title = str(win.get("title", "") or "").strip()
    title = re.sub(r"\s+-\s+[A-Za-z][\w ]*Origin\s*$", "", title).strip()
    return title


def site_allowed(title: str, rules: dict):
    t = title.strip().lower()
    if t in TRANSIENT_TITLES:
        return None
    for entry in rules.get("allow", []):
        pat = str(entry.get("pattern", "")).lower()
        if pat and pat in t:
            return True
    return False


def enforce_sites(app_ok_wins: list, rules: dict, now: float) -> None:
    if not rules:
        return
    grace = int(rules.get("grace_secs", 30))
    live = {str(w.get("address", "")) for w in app_ok_wins}
    for dead in [a for a in VIOLATIONS if a not in live]:
        VIOLATIONS.pop(dead, None)
    for win in app_ok_wins:
        if not is_browser(win, rules):
            continue
        addr = str(win.get("address", ""))
        verdict = site_allowed(page_title(win), rules)
        if verdict is None or verdict is True:
            VIOLATIONS.pop(addr, None)
            continue
        first = VIOLATIONS.get(addr)
        if first is None:
            VIOLATIONS[addr] = now
            log(f"SITE-WARN title={page_title(win)[:60]} addr={addr}")
            notify("Focus Mode", f"Blocked site — window closes in {grace}s")
        elif now - first >= grace:
            ok = close_window(addr)
            log(f"SITE-KILL title={page_title(win)[:60]} addr={addr} closed={ok}")
            if ok:
                VIOLATIONS.pop(addr, None)


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
            wins = hypr_clients()
            survivors = []
            for win in wins:
                addr = str(win.get("address", ""))
                if not addr:
                    continue
                if is_allowed(win, state):
                    survivors.append(win)
                    continue
                ok = close_window(addr)
                log(f"BLOCK class={win.get('class', '?')} addr={addr} closed={ok}")
            enforce_sites(survivors, load_site_rules(), time.time())
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
