# Deployment

One-shot installer for a fresh Debian/Ubuntu/Mint show machine. Same script is the updater.

## First install

```bash
git clone https://github.com/nvdhulst79/LiSP-APCmini-plugin.git ~/dev/lisp-apc-mini-cart
bash ~/dev/lisp-apc-mini-cart/deploy/install.sh
```

What it does (top to bottom, idempotent):

1. Verifies Python ≥ 3.10 and that you're on a Debian-family distro.
2. `apt install` of LiSP's system deps (gstreamer, asound, gobject-introspection, librtmidi, poetry).
3. Clones [linux-show-player](https://github.com/FrancescoCeruti/linux-show-player) (`develop` branch) to `~/dev/linux-show-player` and runs `poetry install`.
4. Clones this plugin repo to `~/dev/lisp-apc-mini-cart`.
5. Symlinks `~/dev/lisp-apc-mini-cart/apc_mini_cart` into `~/dev/linux-show-player/lisp/plugins/apc_mini_cart`.
6. Drops a `lisp-apc` launcher into `~/.local/bin/` and a `.desktop` file into `~/.local/share/applications/` so the app shows up in the menu.

## Updating

```bash
bash ~/dev/lisp-apc-mini-cart/deploy/install.sh
```

Same script. It detects existing clones and `git pull`s them, re-runs `poetry install` (no-op if nothing changed), and refreshes the symlink/launcher.

## Launching

```bash
lisp-apc           # from a terminal
```

Or pick **Linux Show Player (APC)** from your application menu.

## After install, in LiSP

1. Open **Preferences → MIDI** and set both **Input device** and **Output device** to `APC mini mk2 Control` — *not* `APC mini mk2 Notes`. Wrong port = the plugin appears dead.
2. Open or create a Cart Layout session at 8×8.
3. Verify under **Preferences → Plugins** that "APC Mini Cart" is enabled.

## Overrides

The script reads these env vars if you want to deviate from the defaults:

| Var          | Default                                                            |
|--------------|--------------------------------------------------------------------|
| `LISP_DIR`   | `~/dev/linux-show-player`                                          |
| `LISP_REF`   | `develop`                                                          |
| `PLUGIN_DIR` | `~/dev/lisp-apc-mini-cart`                                         |
| `PLUGIN_REF` | `main`                                                             |
| `SKIP_APT`   | unset — set to `1` if you've already installed the system packages |

Example: pin to a specific plugin release tag:

```bash
PLUGIN_REF=v0.2.0 bash ~/dev/lisp-apc-mini-cart/deploy/install.sh
```

## Uninstall

```bash
rm "${HOME}/.local/bin/lisp-apc"
rm "${HOME}/.local/share/applications/lisp-apc.desktop"
rm "${HOME}/dev/linux-show-player/lisp/plugins/apc_mini_cart"   # the symlink
rm -rf "${HOME}/dev/lisp-apc-mini-cart" "${HOME}/dev/linux-show-player"  # optional
```

System packages (apt) are left in place — remove manually if you want.
