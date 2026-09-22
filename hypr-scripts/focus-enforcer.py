#!/usr/bin/env python3
"""Focus Mode enforcer daemon for Hyprland.

Layer 1 (apps): windows already open at session start are grandfathered
(left alone). Only NEW windows opened after start are checked: if their
class is not in the allowlist they are closed instantly.

Layer 2 (sites, foreground-tab only): browser windows that pass layer 1
are title-checked against site-allowlist.json. A settled, non-matching
title triggers a warning; if still violating after grace_secs the window
is closed. Background tabs are invisible in the title and unchecked until
viewed (per user choice).

Reads: ~/.config/focus-mode/state.json, site-allowlist.json
Writes: ~/.config/focus-mode/enforcer.log
Stops when state.json has {"active": false} or disappears.
"""
import glob
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "focus-mode"
STATE_FILE = CONFIG_DIR / "state.json"
SITE_FILE = CONFIG_DIR / "site-allowlist.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
PID_FILE = CONFIG_DIR / "enforcer.pid"
LOG_FILE = CONFIG_DIR / "enforcer.log"

POLL_INTERVAL = 2.0
ANNOUNCED: set = set()  # addrs already notified about (notify once each)
VIOLATIONS: dict = {}  # addr -> first-seen timestamp of site violation
_SITE_CACHE: dict = {}  # {"mtime": float, "rules": dict}

# Titles too unsettled to judge (fresh window, page still loading).
TRANSIENT_TITLES = {"", "untitled", "loading", "loading..."}

# Never kill these, even if not in the allowlist (shell / picker / auth /
# our own GUI — the dashboard/quiz must survive the session it manages).
ALWAYS_ALLOW_CLASSES = {
    "focus-gui",
    "fuzzel",
    "dev.noctalia.noctalia",
    "polkit-gnome-authentication-agent-1",
    "polkit-kde-authentication-agent-1",
    "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-wlr",
    "xdg-desktop-portal",
    "hyprpicker",
    "grimblast",
    "slurp",
    "swappy",
    "hyprshot",
}


def log(msg: str) -> None:
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{time.strftime('%F %T')} {msg}\n")
    except OSError:
        pass


def notify(summary: str, body: str = "") -> None:
    # Desktop notifications (subject to DND — history/audit trail only).
    # Prefer Noctalia internal notification, fall back to notify-send.
    try:
        subprocess.run(
            ["noctalia", "msg", "notification-show", summary, body],
            timeout=5, capture_output=True,
        )
    except Exception:
        pass
    try:
        subprocess.run(
            ["notify-send", "--app-name=Focus Mode", summary, body],
            timeout=5, capture_output=True,
        )
    except Exception:
        pass


def load_global_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def play_cue() -> None:
    """Short audio cue for alerts. Opt-in via config.json (default off)."""
    cfg = load_global_config()
    if not cfg.get("sound"):
        return
    name = str(cfg.get("sound_name", "dialog-warning"))
    for cmd in (["canberra-gtk-play", "-i", name],
                ["paplay", f"/usr/share/sounds/freedesktop/stereo/{name}.oga"]):
        try:
            subprocess.run(cmd, timeout=5, capture_output=True)
            return
        except Exception:
            continue


def alert(summary: str, body: str = "", duration_ms: int = 8000,
          icon: int = 3) -> None:
    """DND-proof user alert: Hyprland compositor overlay (hyprctl notify)
    plus the desktop-notification trail plus optional sound cue."""
    text = f"{summary}: {body}" if body else summary
    try:
        subprocess.run(
            ["hyprctl", "notify", str(icon), str(duration_ms), "0", text],
            timeout=10, capture_output=True,
        )
    except Exception as e:
        log(f"hyprctl notify failed: {e}")
    notify(summary, body)
    play_cue()


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


def socket2_path() -> str | None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if sig:
        p = os.path.join(rt, "hypr", sig, ".socket2.sock")
        if os.path.exists(p):
            return p
    matches = glob.glob(os.path.join(rt, "hypr", "*", ".socket2.sock"))
    return matches[0] if matches else None


def is_allowed(win: dict, state: dict, app_block=None) -> bool:
    allowed = {str(c).lower() for c in state.get("allowed", [])}
    cls = str(win.get("class", "") or "").lower()
    init_cls = str(win.get("initialClass", "") or "").lower()
    title = str(win.get("title", "") or "")
    addr = str(win.get("address", ""))
    pid = win.get("pid")

    # 1. Quiz terminal: never kill the exit-quiz dialog.
    if state.get("quiz_active") and pid and pid == state.get("quiz_pid"):
        return True
    if "focus quiz" in title.lower():
        return True
    # 2. System surfaces.
    if cls in ALWAYS_ALLOW_CLASSES or init_cls in ALWAYS_ALLOW_CLASSES:
        return True
    # 2b. Global app blocklist (preset-independent: class or title rules a
    # non-technical user captured from the GUI). Instant kill, no grace,
    # no grandfather exemption.
    if app_blocked(cls, init_cls, title, app_block):
        return False
    # 3. Preset title blocklist (e.g. OpenCode "OC |" terminals in study).
    # Deliberately NOT grandfather-exempt: an already-open opencode window
    # is exactly what this is for. Entries are substrings (case-insensitive)
    # or {"pattern": ..., "regex": true} objects, like the site lists.
    if title_blocked(title, state.get("title_block", [])):
        return False
    # 4. Grandfathered: open before session start -> left alone.
    # Stored as {address: {pid, class}} so a NEW window that reuses a dead
    # window's address does NOT inherit the exemption (Hyprland recycles
    # addresses). Legacy list-of-addresses states are still honored.
    gf = state.get("grandfathered", [])
    if isinstance(gf, dict):
        info = gf.get(addr) or {}
        if pid and info.get("pid") == pid:
            if str(info.get("class", "")).lower() in (cls, init_cls):
                return True
    elif addr in gf:
        return True
    # 5. User allowlist (match class or initialClass, case-insensitive).
    if cls in allowed or init_cls in allowed:
        return True
    return False


def app_blocked(cls: str, init_cls: str, title: str, entries) -> bool:
    """Global app blocklist: {kind: app, class} exact class match, or
    {kind: title, pattern[, regex]} title match. Either kills."""
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        kind = str(e.get("kind", "title")).lower()
        if kind == "app":
            want = str(e.get("class", "")).lower()
            if want and want in (cls, init_cls):
                return True
        else:
            if title_blocked(title, [e]):
                return True
    return False


def title_blocked(title: str, patterns) -> bool:
    t = str(title or "")
    tl = t.lower()
    for entry in patterns or []:
        if isinstance(entry, dict):
            pat = str(entry.get("pattern", ""))
            if not pat:
                continue
            if entry.get("regex"):
                try:
                    if re.search(pat, t, re.IGNORECASE):
                        return True
                except re.error:
                    continue
            elif pat.lower() in tl:
                return True
        elif str(entry) and str(entry).lower() in tl:
            return True
    return False


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
    cls = str(win.get("class", "") or "").lower()
    init_cls = str(win.get("initialClass", "") or "").lower()
    return cls in browsers or init_cls in browsers


def page_title(win: dict) -> str:
    """Window title minus the ' - Brave Origin' style browser suffix."""
    title = str(win.get("title", "") or "").strip()
    title = re.sub(r"\s+-\s+[A-Za-z][\w ]*Origin\s*$", "", title).strip()
    title = re.sub(r"\s+-\s+(Brave|Chromium|Chrome|Firefox)\s*$", "", title,
                   flags=re.IGNORECASE).strip()
    return title


def match_list(title: str, entries: list) -> bool:
    """Case-insensitive substring match (regex when entry asks)."""
    t = title.strip().lower()
    for entry in entries or []:
        pat = str(entry.get("pattern", "")).lower()
        if not pat:
            continue
        if entry.get("regex"):
            try:
                if re.search(pat, t):
                    return True
            except re.error:
                continue
        elif pat in t:
            return True
    return False


def site_allowed(title: str, rules: dict) -> bool | None:
    """True = allowed, False = violation, None = too early to judge.

    Precedence: block wins over allow; allow wins over default-deny.
    (Lets you carve nested exceptions, e.g. allow 'youtube' + block 'shorts'.)
    """
    t = title.strip().lower()
    if t in TRANSIENT_TITLES:
        return None
    if match_list(t, rules.get("block", [])):
        return False
    if match_list(t, rules.get("allow", [])):
        return True
    return False


def enforce_sites(app_ok_wins: list, rules: dict, now: float) -> None:
    """Layer 2: warn on first violation, close after grace_secs.

    Only sees windows that passed the app layer (grandfathered browser
    windows included — that is the point). Background tabs are invisible
    in the title and unchecked until viewed.
    """
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
            short = page_title(win)[:60]
            log(f"SITE-WARN title={short} addr={addr} grace={grace}s")
            alert("Focus Mode",
                  f"Blocked site ({short}) — window closes in {grace}s unless you leave",
                  duration_ms=10000)
        elif now - first >= grace:
            ok = close_window(addr)
            log(f"SITE-KILL title={page_title(win)[:60]} addr={addr} closed={ok}")
            if ok:
                VIOLATIONS.pop(addr, None)
                ANNOUNCED.add(addr)
                alert("Focus Mode", "Closed a window on a blocked site",
                      duration_ms=5000, icon=1)


def enforce_once(state: dict) -> None:
    wins = hypr_clients()
    rules = load_site_rules()
    app_block = rules.get("app_block", [])
    survivors = []
    for win in wins:
        addr = str(win.get("address", ""))
        if not addr:
            continue
        if is_allowed(win, state, app_block):
            survivors.append(win)
            continue
        cls = win.get("class", "?")
        ok = close_window(addr)
        log(f"BLOCK class={cls} title={win.get('title','')[:60]} addr={addr} closed={ok}")
        if addr not in ANNOUNCED:
            ANNOUNCED.add(addr)
            alert("Focus Mode", f"Blocked {cls} — not in this session's allowlist")
    enforce_sites(survivors, rules, time.time())


def event_listener(stop: threading.Event) -> None:
    """Listen to Hyprland socket2 for openwindow events; trigger a sweep."""
    path = socket2_path()
    if not path:
        log("no socket2 found; poll-only mode")
        return
    while not stop.is_set():
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect(path)
            s.settimeout(1.0)
            buf = b""
            while not stop.is_set():
                try:
                    data = s.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode(errors="replace")
                    # e.g. "openwindow>>0x...,workspace,class,title"
                    if text.startswith("openwindow>>"):
                        state = load_state()
                        if state and state.get("active"):
                            time.sleep(0.6)  # let client register for closewindow
                            enforce_once(state)
            s.close()
        except Exception as e:
            log(f"socket2 listener retry: {e}")
            stop.wait(3.0)


def timer_reminders(state: dict, flags: dict) -> None:
    ends_at = state.get("ends_at")
    if not ends_at:
        return
    remaining = ends_at - time.time()
    mins = remaining / 60
    if remaining <= 0 and not flags.get("end"):
        flags["end"] = True
        alert("Focus Mode", "Time is up! Pass the exit quiz to unlock.",
              duration_ms=10000)
        log("timer expired (session stays locked until quiz passed)")
    elif remaining <= 60 and not flags.get("m1"):
        flags["m1"] = True
        alert("Focus Mode", "1 minute left", duration_ms=5000, icon=1)
    elif remaining <= 5 * 60 and not flags.get("m5"):
        flags["m5"] = True
        alert("Focus Mode", "5 minutes left", duration_ms=5000, icon=1)
    elif remaining <= 10 * 60 and not flags.get("m10"):
        flags["m10"] = True
        alert("Focus Mode", "10 minutes left", duration_ms=5000, icon=1)


def main() -> int:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    log("enforcer started")
    stop = threading.Event()
    t = threading.Thread(target=event_listener, args=(stop,), daemon=True)
    t.start()
    flags: dict = {}
    stop_main = threading.Event()

    def _term(_signo, _frame):
        stop_main.set()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    try:
        while not stop_main.is_set():
            state = load_state()
            if not state or not state.get("active"):
                log("state inactive/missing; exiting")
                break
            enforce_once(state)
            timer_reminders(state, flags)
            stop_main.wait(POLL_INTERVAL)
    finally:
        stop.set()
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except OSError:
            pass
        log("enforcer stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
