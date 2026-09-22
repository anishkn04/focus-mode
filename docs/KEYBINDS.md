-- ---------- Focus Mode keybinds ----------
-- Paste into ~/.config/hypr/hyprland.lua (or translate to hyprland.conf),
-- then relogin (Hyprland reads the Lua config once at startup).
--
--  SUPER+CTRL+F pick+start · SUPER+SHIFT+F quiz-stop · SUPER+ALT+F status

hl.bind(mainMod .. "+CTRL+F", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/focus-pick.sh"), { description = "Focus: Start session (picker)" })
hl.bind(mainMod .. "+SHIFT+F", hl.dsp.exec_cmd("kitty --title 'Focus Quiz - answer to unlock' $HOME/.config/hypr/scripts/focus-quiz-term.sh"), { description = "Focus: Stop session (exit quiz)" })
hl.bind(mainMod .. "+ALT+F", hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/focus-status.sh"), { description = "Focus: Status" })
