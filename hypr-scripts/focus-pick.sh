#!/usr/bin/env bash
# Interactive Focus Mode starter (fuzzel-based).
set -u

PRESETS_DIR="$HOME/.config/focus-mode/presets"

sel() {
  fuzzel --dmenu --lines 12 --prompt "$1 " 2>/dev/null || true
}

DUR="$(printf '15m\n25m\n45m\n1h\n2h\n' | sel " Duration")"
[ -z "${DUR:-}" ] && exit 0

PRESET_LIST="$(ls "$PRESETS_DIR" 2>/dev/null | sed 's/\.json$//' | sort)"
CHOICE="$(printf '%s\nCustom (type class names)\n' "$PRESET_LIST" | sel " Preset")"
[ -z "${CHOICE:-}" ] && exit 0

ALLOW=""
PRESET=""
if [ "$CHOICE" = "Custom (type class names)" ]; then
  ALLOW="$(printf '' | fuzzel --dmenu --lines 0 --prompt " Classes " --placeholder "kitty, code" 2>/dev/null || true)"
  [ -z "${ALLOW:-}" ] && exit 0
else
  PRESET="$CHOICE"
fi

TOPIC="$(printf 'Skip topic\n' | fuzzel --dmenu --lines 8 --prompt "Topic: " 2>/dev/null || true)"
[ -z "${TOPIC:-}" ] && exit 0
[ "$TOPIC" = "Skip topic" ] && TOPIC=""

if [ -n "$PRESET" ]; then
  focus-mode start --preset "$PRESET" --duration "$DUR" --topic "$TOPIC"
else
  focus-mode start --duration "$DUR" --allow "$ALLOW" --topic "$TOPIC"
fi
