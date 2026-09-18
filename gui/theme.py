"""Focus GUI design tokens + QSS builders (v1)."""

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


def build_qss(p: dict) -> str:
    return f"""
QMainWindow, QDialog, QWidget#root {{ background: {p['bg']}; }}
QLabel {{ color: {p['text']}; }}
QLabel#title {{ color: {p['accent']}; font-size: 20px; font-weight: bold; }}
QLineEdit, QComboBox {{
    background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px; padding: 7px;
}}
QComboBox QAbstractItemView {{
    background: {p['surface']}; color: {p['text']};
    selection-background-color: {p['accent']};
    selection-color: {p['accent_ink']};
}}
QPushButton {{
    background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 8px; padding: 9px;
}}
QPushButton#primary {{
    background: {p['accent']}; color: {p['accent_ink']};
    border: none; font-weight: bold;
}}
QPushButton#option {{ text-align: left; padding: 10px; }}
"""
