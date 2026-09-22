# Focus Mode — Zen-style focus sessions for Hyprland

Only allowlisted apps may open new windows. Browser tabs are checked
against a site allowlist (warn, then close). Notifications go quiet.
Exiting takes an AI quiz about your topic. Bailing out takes work too.

Built for **Hyprland** (Linux). Optional Qt dashboard included.

## Features

- **App allowlist** — presets (`code`, `study`, `writing`, `minimal`) + custom picks; non-allowed windows closed instantly; already-open windows grandfathered (address+pid tracked, Hyprland recycles addresses)
- **Site policy** — foreground-tab title matching: allowlist, blocklist (wins over allow), Do-Not-Disturb-proof warnings via compositor overlay, 30s grace
- **App/title blocks** — kill distracting apps by class or window title, every preset (+ per-preset title blocks)
- **Quiz-locked exit** — adaptive 3–10 MCQs from a local LLM (LMStudio, auto-load/unload) or BYOK; self-review fallback; `cancel` requires written answers + typed confirm
- **Qt GUI** — dashboard, button-driven quiz, settings (appearance/alerts/sites/session), Noctalia-blue + system themes
- **Fuzzel flows** — picker, matching Noctalia theme

## Install

**AUR (Arch/CachyOS):**
```bash
yay -S focus-mode
```

**Portable tarball (any Linux):**
```bash
curl -L https://github.com/anishkn04/focus-mode/releases/latest/download/focus-mode.tar.gz | tar xz
cd focus-mode
./install.sh            # ~/.local layout; --prefix /usr/local --no-gui available
```

**From source:**
```bash
git clone https://github.com/anishkn04/focus-mode && cd focus-mode
./install.sh
```

Then add the keybinds from [`docs/KEYBINDS.md`](docs/KEYBINDS.md) to your
`hyprland.lua` (or `.conf`) and relogin.

### Requirements

Required: `hyprland`, `jq`, `python3`, `fuzzel`.
Optional (graceful fallbacks built in): `noctalia`, `kitty`, LMStudio + a chat model.

## Usage

```bash
focus-mode pick                                    # interactive starter
focus-mode start --preset study --duration 25m --topic "thermodynamics"
focus-mode status   # st
focus-mode stop     # quiz (q)   ·   focus-mode cancel  # earned bailout (c)
focus-mode sites    # w          ·   focus-mode gui     # dashboard (g)
focus-mode help
```

See [`docs/KEYBINDS.md`](docs/KEYBINDS.md) for the Hyprland binds
(`SUPER+CTRL+F` picker, `SUPER+SHIFT+F` quiz, `SUPER+ALT+F` status).

## Layout

```
bin/focus-mode          CLI (bash)
hypr-scripts/           enforcer daemon, quiz backend, fuzzel flows
config/presets/         app presets (+ per-preset title blocks)
config/site-allowlist.json   browsers, grace, allow/block/app_block
config/config.json      theme, sound, session defaults
gui/                    Qt dashboard (app.py, theme.py)
launcher/               .desktop entry + enso icon (SVG)
docs/                   keybind snippet
```

## Uninstall

```bash
./install.sh --uninstall
# or: yay -R focus-mode
```

## License

MIT — see [LICENSE](LICENSE).
