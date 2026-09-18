"""Focus Mode Qt dashboard (redesigned).

Thin GUI over the existing CLI/backend — no session logic lives here:
- reads state.json for status (2s refresh); CONFIG_DIR overridable via
  FOCUS_MODE_CONFIG_DIR for fixture-based tests (live files untouched)
- shells out to ~/.local/bin/focus-mode for start/unlock
  (cancellation is terminal-only, deliberately — no GUI path)
- MCQ quiz dialog imports focus-quiz.py backend (generate only; asking is native)
- theme.py tokens; WM_CLASS "focus-gui" (enforcer-exempt)

Run: focus-gui/.venv/bin/python app.py [--smoke]
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("FOCUS_MODE_CONFIG_DIR",
                                 str(HOME / ".config" / "focus-mode")))
PRESETS_DIR = CONFIG_DIR / "presets"
STATE_FILE = CONFIG_DIR / "state.json"
SITE_FILE = CONFIG_DIR / "site-allowlist.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
FOCUS_MODE = str(HOME / ".local" / "bin" / "focus-mode")
QUIZ_PY = str(HOME / ".config" / "hypr" / "scripts" / "focus-quiz.py")

from PySide6.QtCore import Qt, QThread, Signal, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QProgressBar, QPushButton, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

import theme  # noqa: E402


def load_quiz_backend():
    spec = importlib.util.spec_from_file_location("focus_quiz", QUIZ_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def read_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def write_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def run_cli(*args) -> tuple:
    try:
        r = subprocess.run([FOCUS_MODE, *args], capture_output=True,
                           text=True, timeout=30)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def list_presets() -> list:
    try:
        return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))
    except OSError:
        return []


def fill_presets(combo, current: str = "") -> None:
    """Preset combo: capitalized display, lowercase keys as data."""
    combo.clear()
    for name in list_presets():
        combo.addItem(name.capitalize(), name)
    if current:
        idx = combo.findData(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)


def site_summary() -> str:
    try:
        rules = json.loads(SITE_FILE.read_text())
        n = len(rules.get("allow", []))
        return f"{n} sites · {rules.get('grace_secs', 30)}s grace"
    except Exception:
        return "no site policy"


def fmt_remaining(ends_at: float, now: float) -> str:
    rem = max(0, int(ends_at - now))
    h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class QuizWorker(QThread):
    done = Signal(object)
    status = Signal(str)

    def __init__(self, topic, fq):
        super().__init__()
        self.topic = topic
        self.fq = fq

    def run(self):
        try:
            self.fq.set_stage_hook(self.status.emit)
            qs = self.fq.generate_mcq(self.topic, self.fq.lmstudio_ask)
            self.done.emit(qs)
        except Exception as e:  # never kill the UI thread
            self.status.emit(f"Backend error: {e}")
            self.done.emit([])
        finally:
            try:
                self.fq.set_stage_hook(None)
            except Exception:
                pass


class QuizDialog(QDialog):
    LETTERS = "ABCDE"

    def __init__(self, parent, topic, fq):
        super().__init__(parent)
        self.fq = fq
        self.topic = topic
        self.setWindowTitle("Focus Quiz — answer to unlock")
        self.resize(600, 460)
        self.score = 0
        self._qs = []
        self._idx = 0
        self._need = 2
        self._order = []
        self._correct = ""
        self._locked = False
        self._finished = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.counter = QLabel("")
        self.counter.setObjectName("hint")
        self.q = QLabel("Loading questions…")
        self.q.setWordWrap(True)
        self.q.setMinimumHeight(72)
        self.q.setObjectName("heading")
        lay.addWidget(self.progress)
        lay.addWidget(self.counter)
        lay.addWidget(self.q)
        self.btns = []
        for i in range(5):
            b = QPushButton()
            b.setObjectName("option")
            b.clicked.connect(lambda _=False, pos=i: self.answer(pos))
            b.hide()
            lay.addWidget(b)
            self.btns.append(b)
        lay.addStretch(1)
        self.endcard = QLabel("")
        self.endcard.setWordWrap(True)
        self.endcard.hide()
        lay.addWidget(self.endcard)
        self.close_btn = QPushButton("Close")
        self.close_btn.hide()
        self.close_btn.clicked.connect(self.reject)
        lay.addWidget(self.close_btn, alignment=Qt.AlignRight)

        self.worker = QuizWorker(topic, fq)
        self.worker.done.connect(self.on_questions)
        self.worker.status.connect(self.q.setText)
        self.worker.start()

    # -- keyboard-first answers ------------------------------------------
    def keyPressEvent(self, ev):
        t = ev.text().upper()
        if t in self.LETTERS:
            self.answer(self.LETTERS.index(t))
        elif t in "12345":
            self.answer(int(t) - 1)
        else:
            super().keyPressEvent(ev)

    # -- question flow -------------------------------------------------
    def on_questions(self, qs):
        if not qs:
            self.q.setText("Could not get MCQs — no AI backend.")
            self.endcard.setText(
                "Run 'focus-mode stop' in a terminal for self-review,\n"
                "or 'focus-mode cancel' to end now.")
            self.endcard.show()
            self.close_btn.show()
            return
        self._qs = qs
        self._need = self.fq.pass_needed(len(qs))
        for b in self.btns:
            b.show()
        self.show_question()

    def show_question(self):
        import random
        q, opts, ans = self._qs[self._idx]
        order = list(range(len(opts)))
        random.shuffle(order)
        self._order, self._locked = order, False
        self._correct = self.LETTERS[order.index(ans)]
        self.q.setText(q)
        for pos, b in enumerate(self.btns):
            if pos < len(opts):
                b.show()
                b.setText(f"{self.LETTERS[pos]}   {opts[order[pos]]}")
                for prop in ("correct", "wrong", "kbd"):
                    b.setProperty(prop, "false")
                b.style().unpolish(b)
                b.style().polish(b)
                b.setEnabled(True)
            else:
                b.hide()
        self.counter.setText(
            f"Question {self._idx + 1} of {len(self._qs)} · "
            f"score {self.score} · need {self._need}")
        self.progress.setValue(int(100 * self._idx / len(self._qs)))

    def answer(self, pos):
        if self._locked or self._finished or pos >= len(self._order):
            return
        if not self.btns[pos].isVisible():
            return
        self._locked = True
        letter = self.LETTERS[pos]
        for b in self.btns:
            b.setEnabled(False)
        if letter == self._correct:
            self.score += 1
            self.btns[pos].setProperty("correct", "true")
        else:
            self.btns[pos].setProperty("wrong", "true")
            for b, p in zip(self.btns, range(5)):
                if p < len(self._order) and self.LETTERS[p] == self._correct:
                    b.setProperty("correct", "true")
        for b in self.btns:
            b.style().unpolish(b)
            b.style().polish(b)
        self.progress.setValue(int(100 * (self._idx + 1) / len(self._qs)))
        QTimer.singleShot(1100, self.next_step)

    def next_step(self):
        self._idx += 1
        if self._idx >= len(self._qs):
            self.finish()
            return
        self.show_question()

    def finish(self):
        self._finished = True
        for b in self.btns:
            b.hide()
        self.progress.setValue(100)
        if self.score >= self._need:
            code, _ = run_cli("unlock")
            try:
                self.fq.lmstudio_unload()
            except Exception:
                pass
            if code == 0:
                self.counter.setText("Passed")
                self.q.setText(f"{self.score}/{len(self._qs)} — session ended.")
                self.endcard.hide()
                self.close_btn.setText("Done")
                self.close_btn.show()
                return
        self.counter.setText("Still locked")
        self.q.setText(f"{self.score}/{len(self._qs)} — need {self._need}.")
        self.endcard.setText("Session stays locked. Close and retry 'Stop'\n"
                             "when ready — or 'focus-mode cancel' to bail out.")
        self.endcard.show()
        self.close_btn.show()


SOUND_NAMES = ["dialog-warning", "dialog-error", "bell"]


def read_sites() -> dict:
    try:
        return json.loads(SITE_FILE.read_text())
    except Exception:
        return {"browsers": [], "grace_secs": 30, "allow": []}


def write_sites(rules: dict) -> bool:
    try:
        SITE_FILE.write_text(json.dumps(rules, indent=2))
        return True
    except OSError:
        return False


def play_sound(name: str) -> bool:
    for cmd in (["canberra-gtk-play", "-i", name],
                ["paplay", f"/usr/share/sounds/freedesktop/stereo/{name}.oga"]):
        try:
            r = subprocess.run(cmd, timeout=5, capture_output=True)
            if r.returncode == 0:
                return True
        except Exception:
            continue
    return False


class SoundThread(QThread):
    """Play a test cue off the UI thread (a 6s sound used to freeze the app)."""
    finished_ok = Signal(bool)

    def __init__(self, name):
        super().__init__()
        self.name = name

    def run(self):
        self.finished_ok.emit(play_sound(self.name))


class SettingsDialog(QDialog):
    """GNOME-style settings: sidebar nav + stacked pages, all live-applying."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Focus Settings")
        self.resize(640, 480)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(150)
        for label in (" Appearance", " Alerts", " Websites", " Session"):
            self.nav.addItem(label)
        self.stack = QStackedWidget()
        outer.addWidget(self.nav)
        outer.addWidget(self.stack, 1)
        self.pages = {
            " Appearance": self.appearance_page(),
            " Alerts": self.alerts_page(),
            " Websites": self.websites_page(),
            " Session": self.session_page(),
        }
        for label, page in self.pages.items():
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    # -- helpers -------------------------------------------------------
    def card(self, title: str) -> tuple:
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        head = QLabel(title)
        head.setObjectName("heading")
        lay.addWidget(head)
        return frame, lay

    # -- pages ---------------------------------------------------------
    def appearance_page(self) -> QWidget:
        frame, lay = self.card("Appearance")
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["noctalia", "system"])
        self.theme_combo.setCurrentText(read_config().get("theme", "noctalia"))
        self.theme_combo.currentTextChanged.connect(self.switch_theme)
        row.addWidget(self.theme_combo)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel("System follows your OS light/dark mode.\nNoctalia is the signature dark blue.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return frame

    def switch_theme(self, name):
        from PySide6.QtWidgets import QApplication as QA
        cfg = read_config()
        cfg["theme"] = name
        write_config(cfg)
        QA.instance().setStyleSheet(
            theme.build_qss(theme.palette_for(name, QA.instance())))

    def alerts_page(self) -> QWidget:
        frame, lay = self.card("Session alerts")
        cfg = read_config()
        self.sound_check = QCheckBox("Play a sound with warnings")
        self.sound_check.setChecked(bool(cfg.get("sound", False)))
        self.sound_check.stateChanged.connect(self.save_sound)
        lay.addWidget(self.sound_check)
        row = QHBoxLayout()
        row.addWidget(QLabel("Sound"))
        self.sound_combo = QComboBox()
        self.sound_combo.addItems(SOUND_NAMES)
        cur = str(cfg.get("sound_name", "dialog-warning"))
        if cur in SOUND_NAMES:
            self.sound_combo.setCurrentText(cur)
        else:
            # Legacy/removed name (e.g. alarm-clock-elapsed): fall back.
            self.sound_combo.setCurrentText("dialog-warning")
        self.sound_combo.currentTextChanged.connect(self.save_sound)
        self.test_btn = QPushButton("Test")
        self.test_btn.clicked.connect(self.test_sound)
        row.addWidget(self.sound_combo, 1)
        row.addWidget(self.test_btn)
        lay.addLayout(row)
        hint = QLabel("Warnings always show as an overlay, even with\nDo Not Disturb on. Sound is optional.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return frame

    def save_sound(self):
        cfg = read_config()
        cfg["sound"] = bool(self.sound_check.isChecked())
        cfg["sound_name"] = self.sound_combo.currentText()
        write_config(cfg)

    def test_sound(self):
        self.test_btn.setEnabled(False)
        self.test_btn.setText("…")
        self._snd = SoundThread(self.sound_combo.currentText())
        self._snd.finished_ok.connect(self.sound_done)
        self._snd.finished.connect(lambda: self.test_btn.setEnabled(True))
        self._snd.finished.connect(lambda: self.test_btn.setText("Test"))
        self._snd.start()

    def sound_done(self, ok):
        if not ok:
            self.test_btn.setText("Failed")

    def websites_page(self) -> QWidget:
        frame, lay = self.card("Distracting sites")
        rules = read_sites()
        grow = QHBoxLayout()
        grow.addWidget(QLabel("Warn-then-kill grace"))
        self.grace = QSpinBox()
        self.grace.setRange(5, 300)
        self.grace.setValue(int(rules.get("grace_secs", 30)))
        self.grace.setSuffix(" s")
        self.grace.valueChanged.connect(self.save_grace)
        grow.addWidget(self.grace)
        grow.addStretch(1)
        lay.addLayout(grow)
        lay.addWidget(QLabel("Blocked apps & windows (any app, every preset)"))
        self.applist = QListWidget()
        self.applist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.reload_list("app_block", self.applist)
        lay.addWidget(self.applist, 1)
        approw = QHBoxLayout()
        approw.addStretch(1)
        cap_app = QPushButton("From window…")
        cap_app.clicked.connect(lambda: self.capture_window("apps"))
        rm_app = QPushButton("Remove")
        rm_app.clicked.connect(lambda: self.remove_entry("app_block", self.applist))
        approw.addWidget(cap_app)
        approw.addWidget(rm_app)
        lay.addLayout(approw)
        lay.addWidget(QLabel("Blocked page titles — wins over Allowed, even nested"))
        self.bpatterns, self.bnew_pat = self.pattern_list(
            lay, "block", "e.g. shorts  (blocked even inside allowed sites)",
            capture=lambda: self.capture_window("block"))
        lay.addWidget(QLabel("Allowed page titles (foreground tab only)"))
        self.patterns, self.new_pat = self.pattern_list(
            lay, "allow", "e.g. khan academy  (matches page titles)",
            capture=lambda: self.capture_window("allow"))
        hint = QLabel("Edits apply live — the enforcer reloads this file every sweep.")
        hint.setObjectName("hint")
        lay.addWidget(hint)
        return frame

    def save_grace(self, value):
        rules = read_sites()
        rules["grace_secs"] = int(value)
        write_sites(rules)

    def pattern_list(self, lay, key: str, placeholder: str,
                       capture=None):
        """A (list + add/remove row) bound to one rules key.

        capture: optional zero-arg callback for a "From window…" button
        that pre-fills the add field.
        """
        lst = QListWidget()
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lst.setWordWrap(False)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        add = QPushButton("Add")
        add.setEnabled(False)
        add.clicked.connect(lambda: self.add_entry(key, edit, lst))
        edit.returnPressed.connect(lambda: self.add_entry(key, edit, lst))
        edit.textChanged.connect(
            lambda t: add.setEnabled(bool(t.strip())))
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: self.remove_entry(key, lst))
        self.reload_list(key, lst)
        lay.addWidget(lst, 1)
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(add)
        row.addWidget(remove)
        if capture is not None:
            cap = QPushButton("From window…")
            cap.clicked.connect(capture)
            row.addWidget(cap)
        lay.addLayout(row)
        self._add_btns = getattr(self, "_add_btns", {})
        self._add_btns[key] = (add, edit)
        return lst, edit

    @staticmethod
    def entry_text(e: dict) -> tuple:
        """(short display, full tooltip) for allow/block/app entries."""
        if e.get("kind") == "app":
            short = e.get("label") or e.get("class", "")
            full = f"app class: {e.get('class', '')}"
            return short, full
        pat = e.get("pattern", "")
        label = e.get("label") or pat
        short = label if label == pat else f"{label}"
        full = pat if label == pat else f"{pat} — {label}"
        return short, full

    def reload_list(self, key: str, lst):
        rules = read_sites()
        lst.clear()
        for e in rules.get(key, []):
            short, full = self.entry_text(e if isinstance(e, dict) else {})
            item = QListWidgetItem(short)
            item.setToolTip(full)
            lst.addItem(item)

    def add_entry(self, key: str, edit, lst):
        pat = edit.text().strip().lower()
        if not pat:
            return
        rules = read_sites()
        existing = {str(e.get("pattern", "")).lower()
                    for e in rules.get(key, [])}
        if pat not in existing:
            rules.setdefault(key, []).append({"pattern": pat, "label": pat})
            write_sites(rules)
        edit.clear()
        self.reload_list(key, lst)

    def capture_window(self, mode: str):
        """mode allow|block: pre-fill that list's add-field with the picked
        page title (trim, then Add). mode apps: one-click class/title block."""
        dlg = WindowPicker(self, mode)
        if dlg.exec() != QDialog.Accepted or not dlg.result:
            return
        action, (cls, title, _is_browser) = dlg.result
        rules = read_sites()
        if mode in ("allow", "block"):
            edit = self.new_pat if mode == "allow" else self.bnew_pat
            edit.setText(title.strip().lower())
            edit.setFocus()
            return
        # apps mode: direct-add, then refresh.
        entries = rules.setdefault("app_block", [])
        if action == "app":
            if cls.lower() not in {str(e.get("class", "")).lower()
                                   for e in entries if e.get("kind") == "app"}:
                entries.append({"kind": "app", "class": cls,
                                "label": f"{cls} (app)"})
        else:
            pat = title.strip().lower()
            if pat and pat not in {str(e.get("pattern", "")).lower()
                                   for e in entries if e.get("kind") == "title"}:
                entries.append({"kind": "title", "pattern": pat,
                                "label": f"{title.strip()[:50]} (title)"})
        write_sites(rules)
        self.reload_list("app_block", self.applist)

    def remove_entry(self, key: str, lst):
        row = lst.currentRow()
        if row < 0:
            return
        rules = read_sites()
        entries = rules.get(key, [])
        if 0 <= row < len(entries):
            entries.pop(row)
            write_sites(rules)
            self.reload_list(key, lst)

    def session_page(self) -> QWidget:
        frame, lay = self.card("Session defaults")
        cfg = read_config()
        form = QFormLayout()
        form.setSpacing(8)
        self.def_preset = QComboBox()
        fill_presets(self.def_preset, str(cfg.get("default_preset", "")))
        self.def_preset.currentIndexChanged.connect(self.save_session_defs)
        self.def_duration = QLineEdit()
        self.def_duration.setPlaceholderText("25m")
        self.def_duration.setText(str(cfg.get("default_duration", "")))
        self.def_duration.textChanged.connect(self.save_session_defs)
        form.addRow("Default preset", self.def_preset)
        form.addRow("Default duration", self.def_duration)
        lay.addLayout(form)
        hint = QLabel("Used to pre-fill the dashboard. Formats: 25, 25m, 1h, 1h30m.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return frame

    def save_session_defs(self):
        cfg = read_config()
        cfg["default_preset"] = str(self.def_preset.currentData() or "")
        cfg["default_duration"] = self.def_duration.text().strip()
        write_config(cfg)


ENF_PY = str(HOME / ".config" / "hypr" / "scripts" / "focus-enforcer.py")


def load_enforcer():
    spec = importlib.util.spec_from_file_location("focus_enf", ENF_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_windows() -> list:
    """Live windows as (class, title, is_browser). Own GUI + fuzzel filtered."""
    try:
        r = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True,
                           text=True, timeout=8)
        wins = json.loads(r.stdout or "[]")
    except Exception:
        return []
    try:
        enf = load_enforcer()
        skip = {c.lower() for c in enf.ALWAYS_ALLOW_CLASSES} | {"focus-gui"}
        strip = enf.page_title
    except Exception:
        skip, strip = {"fuzzel", "focus-gui"}, (lambda w: str(w.get("title", "")))
    out = []
    for w in wins:
        cls = str(w.get("class", "") or "")
        if not cls or cls.lower() in skip:
            continue
        out.append((cls, strip(w), False))
    # mark browsers via site rules
    try:
        browsers = {str(b).lower() for b in read_sites().get("browsers", [])}
        out = [(c, t, c.lower() in browsers) for c, t, _ in out]
    except Exception:
        pass
    return sorted(out, key=lambda x: (not x[2], x[0].lower()))


class WindowPicker(QDialog):
    """Pick a live window. Site tabs pre-fill the add-field for trimming;
    apps mode offers one-click class/title blocks."""

    def __init__(self, parent, mode: str):
        super().__init__(parent)
        self.mode = mode  # allow | block | apps
        self.setWindowTitle("Pick a window")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        hint = QLabel("Choose a window running right now.")
        hint.setObjectName("hint")
        lay.addWidget(hint)
        self.list = QListWidget()
        self.rows = fetch_windows()
        if not self.rows:
            self.list.addItem("(no windows found — is Hyprland running?)")
            self.list.setEnabled(False)
        for cls, title, is_browser in self.rows:
            tag = "🌐" if is_browser else "🗔"
            shown = f"{tag} {cls} — {title or '(no title)'}"
            item = QListWidgetItem(shown)
            item.setToolTip(f"class: {cls}\ntitle: {title}")
            self.list.addItem(item)
        if self.rows:
            self.list.setCurrentRow(0)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        if mode == "apps":
            self.b_app = QPushButton("Block app")
            self.b_app.setObjectName("danger")
            self.b_app.clicked.connect(lambda: self.choose("app"))
            self.b_title = QPushButton("Block title")
            self.b_title.clicked.connect(lambda: self.choose("title"))
            row.addWidget(self.b_app)
            row.addWidget(self.b_title)
        else:
            self.b_use = QPushButton("Use page title")
            self.b_use.setObjectName("primary")
            self.b_use.clicked.connect(lambda: self.choose("use"))
            row.addWidget(self.b_use)
        lay.addLayout(row)
        self.result = None

    def current(self):
        r = self.list.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def choose(self, action):
        cur = self.current()
        if cur is None:
            return
        self.result = (action, cur)
        self.accept()


class Chip(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("chip")


class Dashboard(QMainWindow):
    def __init__(self, fq):
        super().__init__()
        self.fq = fq
        self.setWindowTitle("Focus Mode")
        self.resize(520, 620)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        title = QLabel("Focus Mode")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        # Hero card: timer + topic.
        self.hero = QLabel()
        self.hero.setObjectName("herocard")
        self.hero.setAlignment(Qt.AlignCenter)
        self.hero.setMinimumHeight(120)
        lay.addWidget(self.hero)
        self.timer_big = QLabel("--:--")
        self.timer_big.setObjectName("display")
        self.timer_big.setAlignment(Qt.AlignCenter)
        self.topic_lbl = QLabel("")
        self.topic_lbl.setAlignment(Qt.AlignCenter)
        herolay = QVBoxLayout(self.hero)
        herolay.addWidget(self.timer_big)
        herolay.addWidget(self.topic_lbl)

        # Chips row.
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chip_preset = Chip("Preset: —")
        self.chip_apps = Chip("Apps: —")
        self.chip_sites = Chip(site_summary())
        for c in (self.chip_preset, self.chip_apps, self.chip_sites):
            chips.addWidget(c)
        chips.addStretch(1)
        lay.addLayout(chips)

        # Setup form (idle only), pre-filled from session defaults.
        cfg = read_config()
        self.form_wrap = QWidget()
        form = QFormLayout(self.form_wrap)
        form.setSpacing(8)
        presets = list_presets()
        self.preset = QComboBox()
        fill_presets(self.preset, str(cfg.get("default_preset", "")))
        self.duration = QComboBox()
        self.duration.setEditable(True)
        self.duration.addItems(["15m", "25m", "45m", "1h", "1h30m", "2h"])
        if str(cfg.get("default_duration", "")).strip():
            self.duration.setCurrentText(str(cfg.get("default_duration")).strip())
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("what are you focusing on?")
        form.addRow("Preset", self.preset)
        form.addRow("Duration", self.duration)
        form.addRow("Topic", self.topic)
        lay.addWidget(self.form_wrap)

        # Inline error banner (no modal spam).
        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)

        # Single primary action + quiet secondary row (settings only —
        # cancellation lives in the terminal, deliberately).
        self.primary = QPushButton("Start session")
        self.primary.setObjectName("primary")
        self.primary.clicked.connect(self.primary_action)
        lay.addWidget(self.primary)
        row = QHBoxLayout()
        self.settings_btn = QPushButton("⚙ Settings")
        self.settings_btn.clicked.connect(lambda: SettingsDialog(self).exec())
        row.addStretch(1)
        row.addWidget(self.settings_btn)
        lay.addLayout(row)
        lay.addStretch(1)
        hint = QLabel("Stop opens the MCQ quiz · bailouts live in the terminal only")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    # -- behavior ------------------------------------------------------
    def refresh(self):
        s = read_state()
        if not s.get("active"):
            self.timer_big.setText("--:--")
            self.topic_lbl.setText("Pick a preset and start.")
            self.chip_preset.setText("Preset: —")
            self.chip_apps.setText("Apps: —")
            self.form_wrap.show()
            self.primary.setText("Start session")
            self.primary.setObjectName("primary")
            return
        now = time.time()
        self.timer_big.setText(fmt_remaining(s.get("ends_at", now), now))
        self.topic_lbl.setText(str(s.get("topic") or "(no topic)"))
        self.chip_preset.setText(f"Preset: {s.get('preset') or 'custom'}")
        self.chip_apps.setText(f"Apps: {len(s.get('allowed', []))}")
        self.form_wrap.hide()
        self.primary.setText("Stop — exit quiz")

    def primary_action(self):
        if read_state().get("active"):
            self.stop()
        else:
            self.start()

    def start(self):
        self.error.hide()
        args = ["start", "--preset", str(self.preset.currentData() or ""),
                "--duration", self.duration.currentText(),
                "--topic", self.topic.text().strip()]
        code, out = run_cli(*args)
        if code != 0:
            self.error.setText(out or "could not start session")
            self.error.show()
        self.refresh()

    def stop(self):
        s = read_state()
        if not s.get("active"):
            return
        # NOTE: not calling `focus-mode stop` — that opens the terminal quiz
        # too. The dialog below IS the quiz (focus-gui is enforcer-exempt).
        if not (s.get("topic") or "").strip():
            self.error.setText("No topic set — run 'focus-mode stop' in a "
                               "terminal for self-review, or 'focus-mode "
                               "cancel' there to bail out.")
            self.error.show()
            return
        QuizDialog(self, s.get("topic").strip(), self.fq).exec()
        self.refresh()


def apply_theme(app) -> None:
    name = read_config().get("theme", "noctalia")
    app.setStyleSheet(theme.build_qss(theme.palette_for(name, app)))


def main() -> int:
    smoke = "--smoke" in sys.argv
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setApplicationName("focus-gui")
    try:
        app.setDesktopFileName("focus-gui")
    except Exception:
        pass
    apply_theme(app)
    fq = load_quiz_backend()
    dash = Dashboard(fq)
    if smoke:
        # No QuizDialog: its worker would fire a real LLM call.
        dash.show()
        app.processEvents()
        print(f"SMOKE-OK dash-visible={dash.isVisible()} "
              f"quizdialog-importable={QuizDialog is not None}")
        print(f"SMOKE-OK presets={list_presets()} "
              f"state-active={bool(read_state().get('active'))}")
        return 0
    dash.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
