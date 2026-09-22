#!/usr/bin/env bash
# Focus Mode installer — portable layout, XDG-respecting, no root needed.
#   ./install.sh [--prefix ~/.local] [--no-gui] [--uninstall]
set -u

PREFIX="$HOME/.local"
WITH_GUI=1
UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix=*) PREFIX="${1#--prefix=}" ;;
    --prefix) PREFIX="${2:-$HOME/.local}"; shift ;;
    --no-gui) WITH_GUI=0 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)
      echo "usage: install.sh [--prefix DIR] [--no-gui] [--uninstall]"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
  shift
done

SRC="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$PREFIX/bin"
HYPR_DIR="$HOME/.config/hypr/scripts"
CONF_DIR="$HOME/.config/focus-mode"
APP_DIR="$HOME/.local/share/applications"
ICON_BASE="$HOME/.local/share/icons/hicolor"

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing required dep: $1" >&2; return 1; }; }
opt()  { command -v "$1" >/dev/null 2>&1 || echo "optional, skipping: $1 ($2)"; }

if [ "$UNINSTALL" = 1 ]; then
  for f in "$BIN_DIR/focus-mode" "$HYPR_DIR"/focus-enforcer.py \
           "$HYPR_DIR"/focus-quiz.py "$HYPR_DIR"/focus-pick.sh \
           "$HYPR_DIR"/focus-quiz-term.sh "$HYPR_DIR"/focus-status.sh \
           "$APP_DIR/focus-gui.desktop"; do
    [ -L "$f" ] && rm "$f" && echo "removed $f"
  done
  echo "config kept at $CONF_DIR (delete manually to wipe sessions/presets)"
  exit 0
fi

echo "== checking dependencies =="
missing=0
for dep in hyprctl jq python3 fuzzel; do need "$dep" || missing=1; done
[ "$missing" = 1 ] && { echo "install the missing deps first" >&2; exit 1; }
opt noctalia "notifications fall back to notify-send"
opt kitty "quiz opens in any terminal"
opt lms "quiz auto-loads LMStudio models; self-review otherwise"

echo "== installing (PREFIX=$PREFIX) =="
mkdir -p "$BIN_DIR" "$HYPR_DIR" "$CONF_DIR/presets" "$CONF_DIR/gui" "$APP_DIR"
ln -sfn "$SRC/bin/focus-mode" "$BIN_DIR/focus-mode"
for sc in focus-enforcer.py focus-quiz.py focus-pick.sh focus-quiz-term.sh focus-status.sh; do
  ln -sfn "$SRC/hypr-scripts/$sc" "$HYPR_DIR/$sc"
  chmod +x "$HYPR_DIR/$sc"
done
for p in "$SRC"/config/presets/*.json; do
  [ -f "$CONF_DIR/presets/$(basename "$p")" ] || cp "$p" "$CONF_DIR/presets/"
done
for c in site-allowlist.json config.json; do
  [ -f "$CONF_DIR/$c" ] || cp "$SRC/config/$c" "$CONF_DIR/"
done

if [ "$WITH_GUI" = 1 ]; then
  ln -sfn "$SRC/gui/app.py" "$CONF_DIR/gui/app.py"
  ln -sfn "$SRC/gui/theme.py" "$CONF_DIR/gui/theme.py"
  if python3 -c "import PySide6" 2>/dev/null; then
    GUI_PY="$(command -v python3)"; echo "PySide6 present (system)"
  else
    echo "creating GUI venv (PySide6)…"
    python3 -m venv "$CONF_DIR/gui/.venv"
    "$CONF_DIR/gui/.venv/bin/pip" install -q -r "$SRC/gui/requirements.txt"
    GUI_PY="$CONF_DIR/gui/.venv/bin/python"
  fi
  sed "s|^Exec=.*|Exec=$GUI_PY $CONF_DIR/gui/app.py|" \
    "$SRC/launcher/focus-gui.desktop" > "$APP_DIR/focus-gui.desktop"
  shopt -s nullglob
  for d in scalable 16x16 48x48 128x128; do
    mkdir -p "$ICON_BASE/$d/apps"
    for icon in "$SRC"/launcher/icons/$d/apps/focus-gui.*; do
      [ -f "$icon" ] && cp "$icon" "$ICON_BASE/$d/apps/"
    done
  done
  shopt -u nullglob
  [ -f "$SRC/launcher/icons/index.theme" ] && cp "$SRC/launcher/icons/index.theme" "$ICON_BASE/" 2>/dev/null || true
  gtk-update-icon-cache -f "$ICON_BASE" >/dev/null 2>&1 || true
  echo "GUI installed — launch with: focus-mode gui"
else
  echo "GUI skipped (--no-gui)"
fi

echo "== verifying =="
bash -n "$BIN_DIR/focus-mode" && echo "cli syntax ok"
python3 -m py_compile "$SRC"/hypr-scripts/*.py && echo "backend syntax ok"
echo
echo "DONE. Next (manual): paste docs/KEYBINDS.md binds into hyprland.lua and relogin."
echo "Try: focus-mode pick"
