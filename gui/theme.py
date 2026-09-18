"""Focus GUI design tokens + QSS builders.

Single source of truth for spacing, type and color. Every widget references
these tokens — no ad-hoc hex in app code.

Themes:
  noctalia — signature dark theme (primary a7c8ff on surface 111318).
  system   — follows the OS color scheme (dark/light via Qt style hints),
             keeping the Noctalia accent for primary actions.
"""

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
TYPE = {"display": 40, "title": 17, "body": 13, "caption": 11}
RADIUS = {"sm": 6, "md": 8, "lg": 14}

NOCTALIA = {
    "bg": "#111318",
    "surface": "#1a1e26",
    "surface_hi": "#232936",
    "text": "#e1e2e9",
    "muted": "#8a93a6",
    "accent": "#a7c8ff",
    "accent_hi": "#c3d8ff",
    "accent_ink": "#111318",
    "pressed": "#273141",
    "border": "#2c3340",
    "danger": "#ffb4ab",
    "ok": "#7ddba3",
}

SYSTEM_DARK = {
    "bg": "#1e1e1e",
    "surface": "#2d2d2d",
    "surface_hi": "#383838",
    "text": "#f0f0f0",
    "muted": "#9a9a9a",
    "accent": "#a7c8ff",
    "accent_hi": "#c3d8ff",
    "accent_ink": "#111318",
    "pressed": "#3a3a3a",
    "border": "#3d3d3d",
    "danger": "#ff8a80",
    "ok": "#7ddba3",
}

SYSTEM_LIGHT = {
    "bg": "#f2f2f2",
    "surface": "#ffffff",
    "surface_hi": "#e8e8e8",
    "text": "#1a1a1a",
    "muted": "#6e6e6e",
    "accent": "#0b57d0",
    "accent_hi": "#0842a0",
    "accent_ink": "#ffffff",
    "pressed": "#d3e3fd",
    "border": "#c4c7c5",
    "danger": "#b3261e",
    "ok": "#146c2e",
}


def build_qss(p: dict) -> str:
    s = SPACING
    return f"""
* {{ font-size: {TYPE['body']}px; }}
QMainWindow, QDialog, QWidget#root {{ background: {p['bg']}; }}
QLabel {{ color: {p['text']}; }}
QLabel#display {{
    color: {p['text']}; font-size: {TYPE['display']}px; font-weight: 300;
}}
QLabel#title {{ color: {p['accent']}; font-size: {TYPE['title']}px; font-weight: bold; }}
QLabel#heading {{ color: {p['text']}; font-size: {TYPE['title']}px; font-weight: bold; }}
QLabel#body {{ color: {p['text']}; }}
QLabel#muted, QLabel#hint {{ color: {p['muted']}; font-size: {TYPE['caption']}px; }}
QLabel#chip {{
    background: {p['surface_hi']}; color: {p['text']};
    border-radius: {RADIUS['lg']}px;
    padding: {s['xs']}px {s['md']}px;
}}
QLabel#herocard {{
    background: {p['surface']}; border-radius: {RADIUS['lg']}px;
}}
QLabel#error {{
    background: {p['surface']}; color: {p['danger']};
    border: 1px solid {p['danger']}; border-radius: {RADIUS['md']}px;
    padding: {s['sm']}px {s['md']}px;
}}
QLineEdit, QComboBox {{
    background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: {RADIUS['md']}px;
    padding: {s['sm']}px {s['md']}px;
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}
QComboBox QAbstractItemView {{
    background: {p['surface']}; color: {p['text']};
    selection-background-color: {p['accent']};
    selection-color: {p['accent_ink']};
}}
QPushButton {{
    background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: {RADIUS['md']}px;
    padding: {s['sm']}px {s['lg']}px;
}}
QPushButton:hover {{ border-color: {p['accent']}; }}
QPushButton:pressed {{ background: {p['pressed']}; }}
QPushButton:disabled {{ color: {p['muted']}; border-color: {p['border']}; }}
QPushButton:focus {{ border: 1px solid {p['accent']}; outline: none; }}
QPushButton#primary {{
    background: {p['accent']}; color: {p['accent_ink']};
    border: none; font-weight: bold; padding: 10px {s['xl']}px;
}}
QPushButton#primary:hover {{ background: {p['accent_hi']}; }}
QPushButton#textbtn {{ background: transparent; border: none; color: {p['muted']}; }}
QPushButton#textbtn:hover {{ color: {p['danger']}; }}
QPushButton#option {{ text-align: left; padding: 12px {s['lg']}px; }}
QPushButton#option[kbd="true"] {{ border-color: {p['accent']}; }}
QPushButton#option[correct="true"] {{
    background: {p['surface']}; border: 1px solid {p['ok']}; color: {p['ok']};
}}
QPushButton#option[wrong="true"] {{
    background: {p['surface']}; border: 1px solid {p['danger']}; color: {p['danger']};
}}
QProgressBar {{
    background: {p['surface']}; border: none; border-radius: {RADIUS['sm']}px;
    max-height: 6px; text-align: center;
}}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: {RADIUS['sm']}px; }}
QFrame#card {{
    background: {p['surface']}; border-radius: {RADIUS['lg']}px;
}}
QListWidget {{
    background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: {RADIUS['md']}px;
    padding: {s['xs']}px; outline: none;
}}
QListWidget::item {{ padding: {s['sm']}px; border-radius: {RADIUS['sm']}px; }}
QListWidget::item:selected {{
    background: {p['pressed']}; color: {p['text']};
    border: 1px solid {p['accent']};
}}
QListWidget#nav {{
    background: transparent; border: none; font-size: {TYPE['body']}px;
}}
QListWidget#nav::item {{ padding: 10px {s['md']}px; }}
QListWidget#nav::item:selected {{
    background: {p['pressed']}; color: {p['accent']}; border: none;
    font-weight: bold;
}}
QCheckBox {{ color: {p['text']}; spacing: {s['sm']}px; }}
QCheckBox::indicator {{
    width: 20px; height: 20px; border-radius: {RADIUS['sm']}px;
    border: 1px solid {p['border']}; background: {p['surface']};
}}
QCheckBox::indicator:checked {{
    background: {p['accent']}; border-color: {p['accent']};
}}
QSpinBox {{
    background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: {RADIUS['md']}px;
    padding: {s['sm']}px {s['md']}px;
}}
QSpinBox:focus {{ border: 1px solid {p['accent']}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {p['surface_hi']}; border: none; width: 22px;
}}
QGroupBox {{
    color: {p['muted']}; border: 1px solid {p['border']};
    border-radius: {RADIUS['md']}px; margin-top: {s['lg']}px;
    padding-top: {s['sm']}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: {s['md']}px; padding: 0 {s['xs']}px;
}}
"""


def detect_system_dark(app) -> bool:
    try:
        from PySide6.QtCore import Qt
        scheme = app.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        return True


def palette_for(theme: str, app=None) -> dict:
    if theme == "system":
        return SYSTEM_DARK if detect_system_dark(app) else SYSTEM_LIGHT
    return NOCTALIA
