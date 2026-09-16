#!/usr/bin/env bash
# Focus Mode status popup (exec_cmd runs without a shell, so no $() inline).
set -u
OUT="$("$HOME/.local/bin/focus-mode" status 2>&1)"
notify-send --app-name="Focus Mode" "Focus Mode" "$OUT" >/dev/null 2>&1 || true
