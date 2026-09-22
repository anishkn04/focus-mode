#!/usr/bin/env bash
# Interactive Focus Mode starter (fuzzel-based).
# Absolute paths throughout: Hyprland exec env may lack ~/.local/bin in PATH.
# Every step is traced to pick.log; failures surface as notifications
# (previously the script failed silently and the session never started).
set -u

CONFIG_DIR="$HOME/.config/focus-mode"
PRESETS_DIR="$CONFIG_DIR/presets"
PICK_LOG="$CONFIG_DIR/pick.log"
FOCUS_MODE="$HOME/.local/bin/focus-mode"

trace() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$PICK_LOG"; }
fail() {
  trace "FAIL: $*"
  noctalia msg notification-show "Focus Mode" "Picker failed: $*" >/dev/null 2>&1 || true
  notify-send --app-name="Focus Mode" "Focus Mode" "Picker failed: $*" >/dev/null 2>&1 || true
  exit 1
}

trace "=== pick started ==="
[ -x "$FOCUS_MODE" ] || fail "focus-mode CLI not found at $FOCUS_MODE"

sel() { # sel <prompt> ; reads options on stdin, prints choice or empty
  fuzzel --dmenu --lines 12 --prompt "$1 " 2>/dev/null || true
}

# Free-text fields pipe EMPTY stdin, which [dmenu] exit-immediately-if-empty
# would kill on sight — override it so the dialog waits for typing.
FREETEXT="--override=dmenu.exit-immediately-if-empty=no"

# 1. Duration
DUR="$(printf '15m\n25m\n45m\n1h\n1h30m\n2h\nCustom...\n' | sel " Duration")"
[ -z "${DUR:-}" ] && { trace "cancelled at duration"; exit 0; }
if [ "$DUR" = "Custom..." ]; then
  DUR="$(printf '' | fuzzel --dmenu $FREETEXT --lines 0 --prompt " Duration " --placeholder "e.g. 25m, 1h" 2>/dev/null || true)"
  [ -z "${DUR:-}" ] && { trace "cancelled at custom duration"; exit 0; }
fi
trace "duration=$DUR"

# 2. Preset
PRESET_LIST="$(ls "$PRESETS_DIR" 2>/dev/null | sed 's/\.json$//' | sort)"
[ -n "$PRESET_LIST" ] || fail "no presets in $PRESETS_DIR"
CHOICE="$(printf '%s\nCustom (pick running apps)\nCustom (type class names)\n' "$PRESET_LIST" | sel " Preset")"
[ -z "${CHOICE:-}" ] && { trace "cancelled at preset"; exit 0; }
trace "choice=$CHOICE"

ALLOW=""
PRESET=""
if [ "$CHOICE" = "Custom (type class names)" ]; then
  ALLOW="$(printf '' | fuzzel --dmenu $FREETEXT --lines 0 --prompt " Classes " --placeholder "kitty, code, …" 2>/dev/null || true)"
  [ -z "${ALLOW:-}" ] && { trace "cancelled at typed classes"; exit 0; }
elif [ "$CHOICE" = "Custom (pick running apps)" ]; then
  # Candidate classes: currently running + common ones.
  RUNNING="$(hyprctl clients -j 2>/dev/null | jq -r '.[].class' 2>/dev/null | sort -u)"
  COMMON="kitty
brave-origin
code
discord
betterbird
joplin
dolphin
subl
vlc
imv
chromium
YouTubeMusic
WhatsApp
WakaLead
Stirling-PDF
io.appflowy.AppFlowy"
  CANDIDATES="$(printf '%s\n%s' "$RUNNING" "$COMMON" | grep -v '^$' | sort -u)"
  PICKED=""
  while true; do
    LIST="$(printf '%s' "$CANDIDATES" | while IFS= read -r c; do
      if printf '%s' ",$PICKED," | grep -qi ",$c,"; then printf '✓ %s\n' "$c"; else printf '  %s\n' "$c"; fi
    done; printf '—— DONE ——\n')"
    SEL="$(printf '%s\n' "$LIST" | sel " Toggle (ENTER on done when set)")"
    [ -z "${SEL:-}" ] && { trace "cancelled at app toggle"; exit 0; }
    if [ "$SEL" = "—— DONE ——" ]; then break; fi
    C="$(printf '%s' "$SEL" | sed 's/^✓* *//')"
    if printf '%s' ",$PICKED," | grep -qi ",$C,"; then
      PICKED="$(printf '%s' "$PICKED" | tr ',' '\n' | grep -vi "^$C$" | paste -sd, -)"
    else
      [ -z "$PICKED" ] && PICKED="$C" || PICKED="$PICKED,$C"
    fi
  done
  [ -z "${PICKED:-}" ] && { trace "cancelled at DONE (empty)"; exit 0; }
  ALLOW="$PICKED"
else
  PRESET="$CHOICE"
  # Optionally add extras on top of preset.
  EXTRA="$(printf 'No extras\nAdd extras...\n' | sel " Extras")"
  [ -z "${EXTRA:-}" ] && { trace "cancelled at extras"; exit 0; }
  if [ "$EXTRA" = "Add extras..." ]; then
    ALLOW="$(printf '' | fuzzel --dmenu $FREETEXT --lines 0 --prompt " Extras " --placeholder "kitty, code, …" 2>/dev/null || true)"
  fi
fi
trace "preset=$PRESET allow=$ALLOW"

# 3. Topic (used by the exit quiz)
TOPIC="$(printf 'Skip topic\n' | fuzzel --dmenu --lines 8 --prompt " Topic " --placeholder "what are you focusing on?" 2>/dev/null || true)"
[ -z "${TOPIC:-}" ] && { trace "cancelled at topic"; exit 0; }
[ "$TOPIC" = "Skip topic" ] && TOPIC=""
trace "topic=$TOPIC"

# 4. Start (capture output so failures are visible, not silent).
START_OUT=""
if [ -n "$PRESET" ]; then
  if [ -n "${ALLOW:-}" ]; then
    START_OUT="$("$FOCUS_MODE" start --preset "$PRESET" --duration "$DUR" --allow "$ALLOW" --topic "$TOPIC" 2>&1)" || fail "$START_OUT"
  else
    START_OUT="$("$FOCUS_MODE" start --preset "$PRESET" --duration "$DUR" --topic "$TOPIC" 2>&1)" || fail "$START_OUT"
  fi
else
  START_OUT="$("$FOCUS_MODE" start --duration "$DUR" --allow "$ALLOW" --topic "$TOPIC" 2>&1)" || fail "$START_OUT"
fi
trace "started ok: $START_OUT"
