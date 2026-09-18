#!/usr/bin/env bash
# Terminal wrapper for the Focus Mode exit quiz.
# Launched as: kitty --title "Focus Quiz - answer to unlock" focus-quiz-term.sh
# Keeps the window open when there is something to read (no session / fail /
# aborted); closes immediately on pass since the session just unlocked.
set -u

QUIZ="$HOME/.config/hypr/scripts/focus-quiz.py"

python3 "$QUIZ"
code=$?

if [ "$code" -eq 0 ]; then
  # Passed + unlocked. Brief confirmation, then close.
  echo "Unlocked — closing..."
  sleep 1
  exit 0
fi

# code 1 = failed/aborted (still locked), 2 = no active session.
echo
if [ -t 0 ]; then
  read -n 1 -r -p "Press any key to close... " _ || true
  echo
else
  # Non-interactive (shouldn't normally happen): don't hang.
  sleep 3
fi
exit "$code"
