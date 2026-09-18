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



def parse_mcq(out: str) -> list:
    """Parse model JSON into [(question, [options], correct_index)]."""
    try:
        t = out.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1]
            t = t.rsplit("```", 1)[0]
        data = json.loads(t)
        if isinstance(data, dict):
            for key in ("questions", "quiz", "items"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        qs = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            q = str(item.get("q") or "").strip()
            opts = [str(o).strip() for o in item.get("options", []) if str(o).strip()]
            ans = item.get("answer", 0)
            if isinstance(ans, str):
                ans = "abcd".find(ans.strip().lower()[:1])
            if q and len(opts) >= 2 and isinstance(ans, int) and 0 <= ans < len(opts):
                qs.append((q, opts, ans))
        return qs
    except Exception:
        return []


def run_mcq(qs) -> tuple | None:
    """Ask MCQs (shuffled), return (score, total). Local deterministic grading."""
    import random
    score, total = 0, 0
    for qi, (q, opts, ans) in enumerate(qs, 1):
        order = list(range(len(opts)))
        random.shuffle(order)
        correct = "ABCD"[order.index(ans)]
        print(f"\n{qi}. {q}")
        for pos, oi in enumerate(order):
            print(f"   {'ABCD'[pos]}. {opts[oi]}")
        try:
            a = input("Your answer (letter): ").strip().upper()[:1]
        except (EOFError, KeyboardInterrupt):
            print("\nQuiz aborted — session stays locked.")
            return None
        total += 1
        if a == correct:
            print("Correct.")
            score += 1
        else:
            print(f"Wrong — the answer was {correct}.")
    return score, total


def main():
    state = load_state()
    if not state.get("active"):
        print("No active Focus Mode session — nothing to unlock.")
        return 2
    topic = (state.get("topic") or "").strip() or "this session"
    print(f"Topic: {topic}\n")
    out = ask_lmstudio(
        "Write between 3 and 10 multiple-choice questions about "
        f"'{topic}' (3 for one concept, more for many sub-topics). "
        "Reply ONLY with JSON: "
        '[{"q": "question?", "options": ["correct", "wrong1", "wrong2", "wrong3"], '
        '"answer": 0}]. Correct answer FIRST.')
    qs = parse_mcq(out or "")[:10]
    if len(qs) < 2:
        print("Could not get MCQs — answer honestly, then unlock manually.")
        return 1
    res = run_mcq(qs)
    if res is None:
        return 1
    score, total = res
    need = max(2, -(-2 * total // 3))
    print(f"\nScore: {score}/{total} (need {need})")
    if score < need:
        print("Not yet — session stays locked.")
        return 1
    print("\nPassed. Unlocking.")
    subprocess.run(["focus-mode", "unlock"])
    lmstudio_unload()
    return 0


if __name__ == "__main__":
    if "--self-review-cancel" in sys.argv:
        sys.exit(0 if self_review("cancel") else 1)
    sys.exit(main())


def self_review(purpose="quiz"):
    print("Answer honestly (one-liners rejected):")
    for p in ["1. What did you work on? ",
              "2. What did you complete/learn? ",
              "3. What is next? "]:
        try:
            a = input(p).strip()
        except (EOFError, KeyboardInterrupt):
            print("Aborted.")
            return False
        if len(a) < 8:
            print("Too short — aborted.")
            return False
    if purpose == "cancel":
        try:
            ok = input("Type END FOCUS to confirm: ").strip() == "END FOCUS"
        except (EOFError, KeyboardInterrupt):
            ok = False
        if not ok:
            print("Wrong phrase — cancel aborted.")
            return False
    return True
