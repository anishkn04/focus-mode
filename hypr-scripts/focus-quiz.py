#!/usr/bin/env python3
"""Focus Mode exit quiz (multiple-choice).

Normal way out of a session: answer MCQs about the focus topic.
- Topic set at session start (-> state.json).
- Tries LMStudio (local, http://localhost:1234) first, then OpenAI-compatible BYOK.
- Server reachable but nothing loaded -> auto-loads an available model via
  `lms load`, and unloads it again after a passed quiz (pre-loaded models
  are left alone).
- No topic or no AI -> self-review fallback (requires real answers, not a free pass).
- Pass (>=2/3) -> runs `focus-mode unlock`.
Stdlib only.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

STATE_FILE = Path.home() / ".config" / "focus-mode" / "state.json"
FOCUS_MODE = str(Path.home() / ".local" / "bin" / "focus-mode")
MCQ_MIN = 3
MCQ_MAX = 10


def pass_needed(n: int) -> int:
    """Proportional bar: ~2/3 correct, at least 2 (3Q->2, 6Q->4, 10Q->7)."""
    return max(2, -(-2 * max(n, 1) // 3))


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


QUIZ_LOG = Path.home() / ".config" / "focus-mode" / "quiz.log"

MODEL_WANT = "huihui"  # quiz uses Huihui exclusively (override: LMSTUDIO_MODEL)


def matches_want(mid: str) -> bool:
    return bool(mid) and MODEL_WANT in mid.lower()

_ON_STAGE = None


def set_stage_hook(fn) -> None:
    """GUI sets this to forward progress (else stages print, CLI-style)."""
    global _ON_STAGE
    _ON_STAGE = fn


def stage(msg: str) -> None:
    """Progress + audit trail: quiz.log always, hook (GUI) or stdout (CLI)."""
    try:
        with open(QUIZ_LOG, "a") as f:
            f.write(f"{time.strftime('%F %T')} {msg}\n")
    except OSError:
        pass
    if _ON_STAGE is not None:
        try:
            _ON_STAGE(msg)
            return
        except Exception:
            pass
    print(f"({msg})")


def server_error(e) -> str:
    """Extract the server's own error message from an HTTPError, else str(e)."""
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = json.loads(e.read().decode())
            msg = body.get("error", {}).get("message") or body
            return f"HTTP {e.code}: {msg}"
        except Exception:
            pass
    return str(e)


def api_root(base: str) -> str:
    return base.replace("/v1", "/api/v1").rstrip("/")


def api_headers() -> dict:
    h = {"Content-Type": "application/json"}
    tok = os.environ.get("LM_API_TOKEN", "")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def api_get(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers=api_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def api_post(url: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=api_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode().strip()
        return json.loads(raw) if raw else {}


def lms_binary() -> str | None:
    """Locate the `lms` CLI (fallback only; server API is preferred)."""
    import shutil
    found = shutil.which("lms")
    if found:
        return found
    cand = Path.home() / ".lmstudio" / "bin" / "lms"
    return str(cand) if cand.exists() else None


def lmstudio_inventory(base: str, timeout: int = 10
                       ) -> tuple[str | None, str | None, str | None]:
    """Return (loaded_key, downloadable_key, instance_id).

    Prefers the v1 management API (true load state); falls back to v0,
    then to the OpenAI-compatible list (ids = downloadable only).
    Embedding models are skipped throughout.
    """
    # v1: GET /api/v1/models
    try:
        data = api_get(api_root(base) + "/models", timeout)
        downloadable = None
        for m in data.get("models", []):
            if str(m.get("type", "")).lower() == "embedding":
                continue
            key = m.get("key", "") or m.get("id", "")
            if not key or not matches_want(key):
                continue
            downloadable = downloadable or key
            insts = m.get("loaded_instances") or []
            if insts:
                inst = insts[0] if isinstance(insts[0], str) else insts[0].get("id", "")
                return key, key, (inst or key)
        return None, downloadable, None
    except Exception:
        pass
    # v0: GET /api/v0/models (state field)
    try:
        data = api_get(base.replace("/v1", "/api/v0") + "/models", timeout)
        downloadable = None
        for m in data.get("data", []):
            mid = m.get("id", "")
            if not mid or "embed" in mid.lower() or not matches_want(mid):
                continue
            downloadable = downloadable or mid
            if str(m.get("state", "")).lower() == "loaded":
                return mid, mid, mid
        return None, downloadable, None
    except Exception:
        pass
    # OpenAI-compatible list: no state, ids are downloadable-only.
    try:
        data = api_get(f"{base}/models", timeout)
        for m in data.get("data", []):
            mid = m.get("id", "")
            if mid and "embed" not in mid.lower() and matches_want(mid):
                return None, mid, None
    except Exception as e:
        stage(f"model list unreachable: {server_error(e)}")
    return None, None, None


def lmstudio_load(base: str, model_key: str, timeout: int = 300) -> bool:
    """Load a downloaded model via the server API (POST /api/v1/models/load).

    Falls back to `lms load` on servers without the v1 endpoint. Rechecks
    state first and verifies serving afterwards — never assume. A forced
    reload over an already-loaded model can crash the engine, so skip it.
    """
    loaded, _, _ = lmstudio_inventory(base)
    if loaded:
        stage(f"model {loaded} appeared meanwhile — using it, no load needed")
        return True
    stage(f"loading {model_key} into memory — one-time wait, can take minutes…")
    via_cli = False
    try:
        api_post(api_root(base) + "/models/load", {"model": model_key},
                 timeout=timeout)
    except Exception as e:
        if "404" in server_error(e):
            via_cli = True
            stage("server has no load endpoint (old LMStudio?) — trying lms CLI")
        else:
            stage(f"load request failed: {server_error(e)}")
            return False
    if via_cli:
        lms = lms_binary()
        if not lms:
            stage("lms CLI not found — load a model in the LMStudio app manually")
            return False
        try:
            r = subprocess.run([lms, "load", "-y", model_key],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                stage(f"lms load failed: {(r.stderr or r.stdout).strip()[-300:]}")
                return False
        except subprocess.TimeoutExpired:
            stage("lms load timed out — the model may still be loading")
            return False
        except Exception as e:
            stage(f"lms load error: {e}")
            return False
    # Verify serving (the POST may return before the engine is ready).
    deadline = time.time() + 120
    while time.time() < deadline:
        loaded, _, _ = lmstudio_inventory(base)
        if loaded:
            stage(f"{loaded} is serving")
            return True
        stage("waiting for engine to report serving…")
        time.sleep(5)
    stage("load finished but the model is not serving — continuing without AI")
    return False


def strip_think(text: str) -> str:
    """Remove <think>…</think> blocks (Qwen3 thinking leaks)."""
    import re
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def chat(messages, *, base=None, key=None, model=None, timeout=60):
    """Minimal OpenAI-compatible chat call. Returns text or None."""
    base = (base or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
    key = key or os.environ.get("OPENAI_API_KEY", "")
    model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if not key and "127.0.0.1" not in base and "localhost" not in base:
        return None
    try:
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps({"model": model, "messages": messages,
                             "temperature": 0.7, "max_tokens": 2000}).encode(),
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})},
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
        stage(f"model answered in {time.time() - t0:.0f}s")
        msg = body["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        if not text and msg.get("reasoning_content"):
            # Thinking leaked despite /no_think: salvage anything usable.
            text = msg.get("reasoning_content").strip()
        return strip_think(text) or None
    except Exception as e:
        stage(f"chat call failed ({model}): {server_error(e)}")
        return None


_LMS_MODEL: str | None = None
_LMS_LOADED_BY_US: bool = False
_LMS_WARM = False  # first inference after a load gets a longer timeout


def lmstudio_ask(messages, retries: int = 1):
    # LMStudio server. Model id must be loaded; empty-but-reachable servers
    # get an available model loaded via the server API (never a blind punt).
    global _LMS_MODEL, _LMS_LOADED_BY_US, _LMS_WARM
    base = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    if _LMS_MODEL is None:
        _LMS_MODEL = os.environ.get("LMSTUDIO_MODEL")  # explicit override wins
    if _LMS_MODEL is None:
        stage("server reachable — checking inventory…")
        loaded, downloadable, _inst = lmstudio_inventory(base)
        if loaded:
            stage(f"using loaded model {loaded}")
            _LMS_MODEL = loaded
        elif downloadable:
            if lmstudio_load(base, downloadable):
                recheck, _, _ = lmstudio_inventory(base)
                _LMS_MODEL = recheck or downloadable
                _LMS_LOADED_BY_US = True
                _LMS_WARM = True
            else:
                return None
        else:
            stage("server is up but has no Huihui model — download one in LMStudio first")
            return None
    timeout = 300 if _LMS_WARM else 90
    for attempt in range(retries + 1):
        if attempt:
            stage(f"requesting again (attempt {attempt + 1})…")
        else:
            stage("requesting from model…")
        out = chat(messages, base=base, key="lm-studio",
                   model=_LMS_MODEL, timeout=timeout)
        if out:
            _LMS_WARM = False  # clear only on real success; cold models stay warm
            return out
    return None


def lmstudio_unload(timeout: int = 60) -> None:
    """Unload the model again — but ONLY if this quiz loaded it.

    Prefers POST /api/v1/models/unload (needs the instance id);
    falls back to `lms unload`. Pre-loaded models are left exactly as found.
    """
    if not _LMS_LOADED_BY_US or not _LMS_MODEL:
        return
    base = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    _, _, inst = lmstudio_inventory(base)
    try:
        api_post(api_root(base) + "/models/unload",
                 {"instance_id": inst or _LMS_MODEL}, timeout=timeout)
        stage(f"unloaded {_LMS_MODEL} — it was auto-loaded for this quiz")
        return
    except Exception as e:
        if "404" not in server_error(e):
            stage(f"server unload failed: {server_error(e)} — trying lms CLI")
        else:
            stage("server has no unload endpoint — trying lms CLI")
    lms = lms_binary()
    if not lms:
        return
    try:
        r = subprocess.run([lms, "unload", _LMS_MODEL],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            stage(f"unloaded {_LMS_MODEL} — it was auto-loaded for this quiz")
        else:
            stage(f"could not unload {_LMS_MODEL}; leaving it loaded")
    except Exception as e:
        stage(f"unload skipped: {e}")


def ai_backend():
    if os.environ.get("OPENAI_API_KEY"):
        return lambda m: chat(m)
    return lmstudio_ask


def parse_mcq(out: str) -> list:
    """Parse model JSON into [(question, [options], correct_index)]. Lenient."""
    s = strip_think(out.strip())
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    data = None
    try:
        data = json.loads(s)
    except Exception:
        start, end = s.find("["), s.rfind("]")
        if 0 <= start < end:
            try:
                data = json.loads(s[start:end + 1])
            except Exception:
                return []
        else:
            return []
    if isinstance(data, dict):
        for key in ("questions", "quiz", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    qs = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        q = str(item.get("q") or item.get("question") or "").strip()
        opts = [str(o).strip() for o in
                (item.get("options") or item.get("choices") or [])
                if str(o).strip()]
        ans = item.get("answer", 0)
        if isinstance(ans, str):
            ans = "abcd".find(ans.strip().lower()[:1])
        if not q or len(opts) < 2 or not isinstance(ans, int):
            continue
        if not 0 <= ans < len(opts):
            continue
        qs.append((q, opts[:5], ans))
    return qs


def generate_mcq(topic, ask) -> list:
    prompt = (
        f"You are a strict but fair study coach. The user did a focus session on: \"{topic}\". "
        f"Write between {MCQ_MIN} and {MCQ_MAX} multiple-choice questions that check whether they actually studied it. "
        "Scale the count to the topic's breadth: 3 for a single concept, more when the "
        "title spans multiple distinct sub-topics (up to 10 for very broad topics). "
        "Reply with ONLY a JSON array, no other text, in this exact shape:\n"
        '[{"q": "question?", "options": ["correct answer", "wrong option 1", "wrong option 2", "wrong option 3"], "answer": 0}]\n'
        "Rules: put the CORRECT answer FIRST in options (answer is always 0); "
        "each question under 15 words; each option under 5 words; "
        "spread questions across ALL sub-topics in the title, not just one.\n"
        "/no_think"
    )
    for attempt in range(2):
        if attempt:
            stage("model answered off-format — retrying with stricter prompt…")
        else:
            stage("requesting MCQs from model…")
        out = ask([{"role": "user", "content": prompt}])
        if not out:
            return []
        qs = parse_mcq(out)
        if len(qs) >= min(2, MCQ_MIN):
            stage(f"parsed {len(qs)} questions")
            return qs[:MCQ_MAX]
        prompt += " Reply with ONLY the JSON array."
    stage("could not parse model output twice — giving up on AI questions")
    return []


def run_mcq(qs) -> tuple | None:
    """Ask MCQs (options shuffled client-side), return (score, total)."""
    import random
    letters = "ABCDE"
    score, total = 0, 0
    for qi, (q, opts, ans) in enumerate(qs, 1):
        order = list(range(len(opts)))
        random.shuffle(order)
        correct = letters[order.index(ans)]
        print(f"\n{qi}. {q}")
        for pos, oi in enumerate(order):
            print(f"   {letters[pos]}. {opts[oi]}")
        try:
            a = input("Your answer (letter): ").strip().upper()[:1]
        except (EOFError, KeyboardInterrupt):
            print("\nQuiz aborted — session stays locked.")
            return None
        total += 1
        if a == correct:
            print("Correct.")
            score += 1
        elif a in letters[:len(opts)]:
            print(f"Wrong — the answer was {correct}.")
        else:
            print(f"Not a valid option — the answer was {correct}.")
    return score, total


def self_review_fallback(topic, purpose="quiz"):
    """Three written answers. purpose='quiz' (stay locked on fail) or
    'cancel' (abort the cancel on fail). Shared by quiz fallback and cancel."""
    abort_msg = ("session stays locked. Try again when ready." if purpose == "quiz"
                 else "cancel aborted.")
    if purpose == "quiz":
        print("No AI backend reachable (LMStudio has no model loaded and no BYOK key set).")
        print("Load a model in LMStudio or set OPENAI_API_KEY for AI-generated questions.\n")
        print("Self-review mode instead:")
    else:
        print("Cancelling takes conscious answers first — no sleepwalking out.\n")
    print("Give honest, non-empty answers. One-liners like 'idk' will be rejected.\n")
    prompts = [
        "1. What specifically did you work on? ",
        "2. What is one thing you learned or completed? ",
        "3. What is still unfinished / next step? ",
    ]
    answers = []
    for p in prompts:
        try:
            a = input(p).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\nAborted — {abort_msg}")
            return False
        if len(a) < 8:
            print(f"Too short — {abort_msg}")
            return False
        answers.append(a)
    return True


def main():
    state = load_state()
    if not state.get("active"):
        print("No active Focus Mode session — nothing to unlock.")
        print("Start one with Super+Ctrl+F (or: focus-mode start --preset minimal --duration 25m).")
        return 2
    topic = (state.get("topic") or "").strip()
    print("=" * 52)
    print("  FOCUS MODE — exit quiz")
    print("  (genuinely stuck? 'focus-mode cancel' bails out — 3 questions + confirm)")
    print("=" * 52)
    if topic:
        print(f"Topic: {topic}\n")
    else:
        print("No topic was set for this session.\n")

    passed = False
    if topic:
        ask = ai_backend()
        qs = generate_mcq(topic, ask)
        if not qs:
            print("Could not get MCQs from an AI backend (see quiz.log for the stage that failed).")
            passed = self_review_fallback(topic)
        else:
            need = pass_needed(len(qs))
            print(f"Answer {len(qs)} multiple-choice questions. "
                  f"Need {need} correct to unlock.\n")
            res = run_mcq(qs)
            if res is None:
                return 1
            score, total = res
            print(f"\nScore: {score}/{total}")
            passed = score >= need
    else:
        passed = self_review_fallback(topic)

    if passed:
        print("\nPassed. Unlocking Focus Mode.")
        time.sleep(0.5)
        subprocess.run([FOCUS_MODE, "unlock"])
        lmstudio_unload()  # only unloads if this quiz loaded the model
        return 0
    print("\nNot yet — session stays locked. Keep focusing, then retry 'focus-mode stop'.")
    return 1


if __name__ == "__main__":
    if "--self-review" in sys.argv:
        # Standalone step used by `focus-mode cancel`: three written answers
        # (+ END FOCUS confirm in cancel mode). Single stdin consumer on
        # purpose: Python's buffered input() would swallow lines meant for
        # a second reader.
        purpose = "cancel" if "--cancel" in sys.argv else "quiz"
        ok = self_review_fallback("", purpose)
        if ok and purpose == "cancel":
            try:
                phrase = input("Type END FOCUS to confirm: ").strip()
            except (EOFError, KeyboardInterrupt):
                phrase = ""
            if phrase != "END FOCUS":
                print("Wrong phrase — cancel aborted.")
                ok = False
        sys.exit(0 if ok else 1)
    sys.exit(main())
