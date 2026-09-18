#!/usr/bin/env bash
# Focus Mode status popup for the SUPER+ALT+F bind.
# A script (not inline $()) because hl.dsp.exec_cmd runs without a shell.
# Uses hyprctl notify so it shows even with Do Not Disturb on.
set -u

OUT="$("$HOME/.local/bin/focus-mode" status 2>&1)"
hyprctl notify 1 6000 0 "$OUT" >/dev/null 2>&1 || \
  notify-send --app-name="Focus Mode" "Focus Mode" "$OUT" >/dev/null 2>&1 || true
