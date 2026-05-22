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
2. `apt install` of LiSP's system deps: gstreamer + its **GObject-introspection typelibs** (`gir1.2-gstreamer-1.0`, `gir1.2-gst-plugins-base-1.0`, `gir1.2-glib-2.0`), asound, `libgirepository-2.0-dev` + `libcairo2-dev` (for the PyGObject/pycairo source builds), `build-essential` + `pkg-config`, **librtmidi7**, **python3-pyqt5 + python3-pyqt5.qtsvg**, poetry. See *Why these packages* below.
3. Clones [linux-show-player](https://github.com/FrancescoCeruti/linux-show-player) (`develop` branch) to `~/lisp/linux-show-player`, configures its poetry venv to inherit system site-packages (so the apt-installed PyQt5 is visible), strips the PyQt5 pins from LiSP's `pyproject.toml` and re-locks (see below), then runs `poetry install`.
4. Clones this plugin repo to `~/lisp/apc-mini-cart`.
5. Symlinks the clone `~/lisp/apc-mini-cart` into `~/lisp/linux-show-player/lisp/plugins/apc_mini_cart` (the repo root *is* the plugin package).
6. Drops a `lisp-apc` launcher into `~/.local/bin/` and a `.desktop` file into `~/.local/share/applications/` so the app shows up in the menu.

## Why these packages (and the PyQt5 dance)

The Pi is `aarch64`. PyPI has **no aarch64 wheel for PyQt5** — neither for `pyqt5` nor for `pyqt5-qt5` (the prebuilt-Qt sub-package), only x86_64 Linux + Windows + macOS. And `pyqt5-qt5` has no buildable sdist (it's just packaged Qt binaries), so there isn't even a slow-source-build fallback: on a Pi, poetry simply fails with *"Unable to find installation candidates for pyqt5-qt5"* and the whole install aborts.

Trixie's apt has `python3-pyqt5` at **5.15.11+dfsg-2** — precompiled for arm64 and exactly the upstream version LiSP's `pyproject.toml` pins (`^5.15.2`). So we install it via apt and make the LiSP venv see it:

```bash
poetry config virtualenvs.options.system-site-packages true --local
```

This writes a `poetry.toml` next to LiSP's `pyproject.toml` (the `--local` flag scopes the setting to LiSP only — your global poetry config is untouched), so the venv inherits the system site-packages directory and the apt PyQt5 (with its bundled `PyQt5.sip`) is importable at runtime.

**But system-site-packages alone is not enough.** It makes PyQt5 *importable*, but poetry still reads `pyqt5`/`pyqt5-qt5` from the lock file and tries to *install* them from PyPI regardless — which fails on arm64 as above. (This is masked on x86_64, where those wheels exist, which is why it only bit on the first real Pi deploy.) So the script also strips the two pins from LiSP's `pyproject.toml` and re-locks:

```bash
sed -i -E '/^pyqt5(-qt5)? = /d' pyproject.toml
poetry lock --no-update    # plain `poetry lock` on poetry 2.x
```

Removing the top-level `pyqt5` drops `pyqt5`, `pyqt5-qt5` and the transitive `pyqt5-sip` from the lock, so `poetry install` stops fetching them — and apt's `python3-pyqt5` covers all three at runtime. The script does this on every run; because it `reset --hard`s the LiSP checkout to the remote tip first, the edit re-applies cleanly each time instead of fighting a `git pull`.

**The other source builds.** PyGObject, pycairo and python-rtmidi *do* have buildable sdists and compile from source on the Pi — that's why `build-essential`, `pkg-config`, `libgirepository-2.0-dev`, `libcairo2-dev` and `libasound2-dev` are in the apt list (meson and ninja come from pip's build isolation, so they aren't needed as system packages). Note `libgirepository-2.0-dev`, **not** the older `1.0` package: on Trixie, PyGObject 3.50+ requires `girepository-2.0`.

**GStreamer needs its typelibs.** PyGObject is only the bridge — the `gi.repository.Gst` namespace loads from `.typelib` files at runtime, which the `gstreamer1.0-plugins-*` packages do *not* pull in. Without `gir1.2-gstreamer-1.0` / `gir1.2-gst-plugins-base-1.0`, LiSP starts (the GUI is PyQt5) but the GStreamer backend silently disables itself and you get no audio.

If LiSP later starts importing a Qt5 module that isn't in `python3-pyqt5` or `python3-pyqt5.qtsvg` (e.g. `QtMultimedia`, `QtOpenGL`), the fix is a one-line `apt install python3-pyqt5.qtXXX` — the apt search index at <https://packages.debian.org/trixie/> lists every sub-package.

## Updating

```bash
bash ~/lisp/apc-mini-cart/deploy/install.sh
```

Same script. It detects existing clones, fetches and `reset --hard`s them to the remote tip (so the local PyQt5 patch re-applies cleanly), re-runs `poetry install` (near-no-op if nothing changed), and refreshes the symlink/launcher. Because the LiSP checkout is reset to the remote, don't keep hand-edits in `~/lisp/linux-show-player` — they'll be discarded on the next run.

## Launching

```bash
lisp-apc           # from a terminal
```

Or pick **Linux Show Player (APC)** from your application menu.

## Boot straight into LiSP (show machine)

For an unattended show box, run the installer with both flags:

```bash
AUTOSTART=1 AUTOLOGIN=1 bash ~/lisp/apc-mini-cart/deploy/install.sh
```

- `AUTOLOGIN=1` enables desktop autologin (via `raspi-config`), so the Pi boots into the desktop without a password.
- `AUTOSTART=1` makes LiSP launch when that desktop session starts. LiSP opens **maximized** on its own, so there's nothing extra to configure for that.

**How the autostart works (and why it's done this way).** RPi OS Trixie's desktop is **labwc** (Wayland).

1. labwc does **not** read `~/.config/autostart/*.desktop` (the freedesktop XDG autostart dir) — the `lxsession-xdg-autostart` line in `/etc/xdg/labwc/autostart` is vestigial under labwc, so a `.desktop` autostart entry silently never fires.
2. This labwc runs **both** `/etc/xdg/labwc/autostart` *and* the user's `~/.config/labwc/autostart` (not "first file wins"). So the user file must contain **only** the LiSP launch line — copying the system lines (`wf-panel-pi`, `pcmanfm-pi`, `kanshi`) into it gives you a duplicate taskbar.

So `AUTOSTART=1` just appends one line — `~/.local/bin/lisp-apc &` — to `~/.config/labwc/autostart` (idempotently; any existing content is left alone). It assumes the labwc desktop; on a different compositor the file is ignored and LiSP simply won't autostart (nothing breaks). To undo it, delete that line from `~/.config/labwc/autostart`.

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
| `AUTOSTART`  | unset — set to `1` to launch LiSP automatically on login (see below) |
| `AUTOLOGIN`  | unset — set to `1` to boot straight to the desktop with no password |

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
