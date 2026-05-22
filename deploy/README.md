# Deployment

One-shot installer for a fresh **Raspberry Pi OS Trixie (64-bit)** show machine. Same script is the updater. Vanilla Debian Trixie on other architectures also works — the apt package names are identical; the script just refuses anything that isn't Trixie.

> **Why Trixie specifically?** Debian renamed the rtmidi runtime soname (`librtmidi6` → `librtmidi7`) at Trixie, and Trixie is the first release that ships `python3-pyqt5` 5.15.11 — the exact version LiSP pins. Targeting one release lets us hardcode package names instead of doing distro-detection gymnastics. Bookworm is not supported.

## First install

```bash
git clone https://github.com/nvdhulst79/LiSP-APCmini-plugin.git ~/lisp/apc-mini-cart
bash ~/lisp/apc-mini-cart/deploy/install.sh
```

What it does (top to bottom, idempotent):

1. Verifies you're on Trixie (refuses to run otherwise; older releases would fail at the apt step anyway).
2. `apt install` of LiSP's system deps: gstreamer, asound, gobject-introspection, **librtmidi7**, **python3-pyqt5 + python3-pyqt5.qtsvg**, poetry. See *Why these packages* below.
3. Clones [linux-show-player](https://github.com/FrancescoCeruti/linux-show-player) (`develop` branch) to `~/lisp/linux-show-player`, configures its poetry venv to inherit system site-packages (so the apt-installed PyQt5 is visible), then runs `poetry install`.
4. Clones this plugin repo to `~/lisp/apc-mini-cart`.
5. Symlinks the clone `~/lisp/apc-mini-cart` into `~/lisp/linux-show-player/lisp/plugins/apc_mini_cart` (the repo root *is* the plugin package).
6. Drops a `lisp-apc` launcher into `~/.local/bin/` and a `.desktop` file into `~/.local/share/applications/` so the app shows up in the menu.

## Why these packages (and the system-site-packages trick)

The Pi is `aarch64`. PyPI has **no aarch64 wheel for PyQt5** — only x86_64 Linux + Windows + macOS. If we let poetry pull PyQt5 from PyPI on a Pi, it falls back to the source distribution and starts a Qt5 + sip compile that takes 20–30 minutes on a Pi 4/5 and needs a pile of `-dev` packages we'd otherwise not install (`qtbase5-dev`, `qttools5-dev-tools`, `qtmultimedia5-dev`, `libqt5svg5-dev`, `sip-tools`, …).

Trixie's apt has `python3-pyqt5` at **5.15.11+dfsg-2** — precompiled for arm64 and exactly the upstream version LiSP's `pyproject.toml` pins (`^5.15.2`). So we install it via apt and then run, inside the LiSP repo:

```bash
poetry config virtualenvs.options.system-site-packages true --local
```

This writes a `poetry.toml` next to LiSP's `pyproject.toml` (the `--local` flag scopes the setting to LiSP only — your global poetry config is untouched). On the subsequent `poetry install`, poetry's venv inherits the system site-packages directory, sees that PyQt5 5.15.11 is already present, and skips it. Trades a half-hour source build for a one-line poetry config and a couple of apt packages.

If LiSP later starts importing a Qt5 module that isn't in `python3-pyqt5` or `python3-pyqt5.qtsvg` (e.g. `QtMultimedia`, `QtOpenGL`), the fix is a one-line `apt install python3-pyqt5.qtXXX` — the apt search index at <https://packages.debian.org/trixie/> lists every sub-package.

## Updating

```bash
bash ~/lisp/apc-mini-cart/deploy/install.sh
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
| `LISP_DIR`   | `~/lisp/linux-show-player`                                         |
| `LISP_REF`   | `develop`                                                          |
| `PLUGIN_DIR` | `~/lisp/apc-mini-cart`                                             |
| `PLUGIN_REF` | `main`                                                             |
| `SKIP_APT`   | unset — set to `1` if you've already installed the system packages |

Example: pin to a specific plugin release tag:

```bash
PLUGIN_REF=v0.2.0 bash ~/lisp/apc-mini-cart/deploy/install.sh
```

## Uninstall

```bash
rm "${HOME}/.local/bin/lisp-apc"
rm "${HOME}/.local/share/applications/lisp-apc.desktop"
rm "${HOME}/lisp/linux-show-player/lisp/plugins/apc_mini_cart"   # the symlink
rm -rf "${HOME}/lisp/apc-mini-cart" "${HOME}/lisp/linux-show-player"  # optional
```

System packages (apt) are left in place — remove manually if you want.
