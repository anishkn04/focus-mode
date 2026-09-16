#!/usr/bin/env bash
# Terminal wrapper for the exit quiz: holds the window unless quiz passes.
set -u
QUIZ="$HOME/.config/hypr/scripts/focus-quiz.py"
python3 "$QUIZ"
code=$?
if [ "$code" -eq 0 ]; then
  echo "Unlocked — closing..."
  sleep 1
  exit 0
fi
echo
if [ -t 0 ]; then
  read -n 1 -r -p "Press any key to close... " _ || true
  echo
else
  sleep 3
fi
exit "$code"
