# Focus Mode keybinds (Hyprland)

Paste into `~/.config/hypr/hyprland.lua`, then **relogin**
(Hyprland reads the Lua config once at startup).

| Bind | Action |
|---|---|
| `SUPER+CTRL+F` | Start session (fuzzel picker) |
| `SUPER+SHIFT+F` | Stop session (exit quiz) |
| `SUPER+ALT+F` | Session status popup |

```lua
-- ---------- Focus Mode ----------
hl.bind(mainMod .. "+CTRL+F",
  hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/focus-pick.sh"),
  { description = "Focus: Start session (picker)" })
hl.bind(mainMod .. "+SHIFT+F",
  hl.dsp.exec_cmd("kitty --title 'Focus Quiz - answer to unlock' $HOME/.config/hypr/scripts/focus-quiz-term.sh"),
  { description = "Focus: Stop session (exit quiz)" })
hl.bind(mainMod .. "+ALT+F",
  hl.dsp.exec_cmd("$HOME/.config/hypr/scripts/focus-status.sh"),
  { description = "Focus: Status" })
```

## `hyprland.conf` users

Translate each line to one `bind`:

```ini
bind = SUPER_CTRL, F, exec, $HOME/.config/hypr/scripts/focus-pick.sh
bind = SUPER_SHIFT, F, exec, kitty --title 'Focus Quiz - answer to unlock' $HOME/.config/hypr/scripts/focus-quiz-term.sh
bind = SUPER_ALT, F, exec, $HOME/.config/hypr/scripts/focus-status.sh
```

Then `hyprctl reload` (no relogin needed for `.conf`).
