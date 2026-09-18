"""Focus Mode Qt dashboard (v1).

Thin GUI over the CLI/backend: reads state.json, shells out to focus-mode,
MCQ quiz dialog imports the quiz backend. WM_CLASS "focus-gui".
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
FOCUS_MODE = str(HOME / ".local" / "bin" / "focus-mode")
QUIZ_PY = str(HOME / ".config" / "hypr" / "scripts" / "focus-quiz.py")

from PySide6.QtCore import Qt, QThread, Signal, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
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


class QuizWorker(QThread):
    done = Signal(object)

    def __init__(self, topic, fq):
        super().__init__()
        self.topic = topic
        self.fq = fq

    def run(self):
        try:
            qs = self.fq.generate_mcq(self.topic, self.fq.lmstudio_ask)
            self.done.emit(qs)
        except Exception:
            self.done.emit([])


class QuizDialog(QDialog):
    def __init__(self, parent, topic, fq):
        super().__init__(parent)
        self.fq = fq
        self.setWindowTitle("Focus Quiz — answer to unlock")
        self.resize(560, 420)
        self.score = 0
        lay = QVBoxLayout(self)
        self.info = QLabel(f"Topic: {topic}")
        self.q = QLabel("Loading questions…")
        self.q.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addWidget(self.q)
        self.btns = []
        for i in range(4):
            b = QPushButton()
            b.setObjectName("option")
            b.clicked.connect(lambda _=False, pos=i: self.answer(pos))
            b.hide()
            lay.addWidget(b)
            self.btns.append(b)
        self.worker = QuizWorker(topic, fq)
        self.worker.done.connect(self.on_questions)
        self.worker.start()

    def on_questions(self, qs):
        if not qs:
            QMessageBox.information(self, "No AI backend",
                                    "Could not get MCQs. Use the terminal instead.")
            self.reject()
            return
        self._qs, self._idx, self._need = qs, 0, min(2, len(qs))
        for b in self.btns:
            b.show()
        self.show_q()

    def show_q(self):
        import random
        q, opts, ans = self._qs[self._idx]
        order = list(range(len(opts)))
        random.shuffle(order)
        self._order, self._correct = order, "ABCD"[order.index(ans)]
        self._locked = False
        self.q.setText(f"{self._idx + 1}. {q}")
        for pos, b in enumerate(self.btns):
            if pos < len(opts):
                b.show()
                b.setText(f"{'ABCD'[pos]}. {opts[order[pos]]}")
                b.setEnabled(True)
            else:
                b.hide()

    def answer(self, pos):
        if self._locked:
            return
        self._locked = True
        self.total = getattr(self, "total", 0) + 1
        for b in self.btns:
            b.setEnabled(False)
        if "ABCD"[pos] == self._correct:
            self.score += 1
        self._idx += 1
        if self._idx >= len(self._qs):
            if self.score >= self._need:
                run_cli("unlock")
                QMessageBox.information(self, "Unlocked", "Session ended.")
                self.accept()
            else:
                QMessageBox.warning(self, "Still locked", "Session stays locked.")
                self.reject()
            return
        self.show_q()


class Dashboard(QMainWindow):
    def __init__(self, fq):
        super().__init__()
        self.fq = fq
        self.setWindowTitle("Focus Mode")
        self.resize(480, 560)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Focus Mode")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        self.status = QLabel("…")
        self.status.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(self.status)
        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItems(list_presets())
        self.duration = QComboBox()
        self.duration.setEditable(True)
        self.duration.addItems(["15m", "25m", "45m", "1h", "2h"])
        self.topic = QLineEdit()
        form.addRow("Preset", self.preset)
        form.addRow("Duration", self.duration)
        form.addRow("Topic", self.topic)
        lay.addLayout(form)
        self.start_btn = QPushButton("Start session")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop — exit quiz")
        self.stop_btn.clicked.connect(self.stop)
        lay.addWidget(self.start_btn)
        lay.addWidget(self.stop_btn)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def refresh(self):
        s = read_state()
        if not s.get("active"):
            self.status.setText("Inactive — pick a preset and start.")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return
        now = time.time()
        rem = max(0, int(s.get("ends_at", now) - now))
        self.status.setText(f"ACTIVE — {rem // 60}m left · {s.get('topic') or '(none)'}")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def start(self):
        code, out = run_cli("start", "--preset", self.preset.currentText(),
                            "--duration", self.duration.currentText(),
                            "--topic", self.topic.text().strip())
        if code != 0:
            QMessageBox.warning(self, "Start failed", out or "unknown error")
        self.refresh()

    def stop(self):
        s = read_state()
        if not s.get("active") or not (s.get("topic") or "").strip():
            return
        QuizDialog(self, s.get("topic").strip(), self.fq).exec()
        self.refresh()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("focus-gui")
    try:
        app.setDesktopFileName("focus-gui")
    except Exception:
        pass
    app.setStyleSheet(theme.build_qss(theme.NOCTALIA))
    fq = load_quiz_backend()
    dash = Dashboard(fq)
    dash.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
