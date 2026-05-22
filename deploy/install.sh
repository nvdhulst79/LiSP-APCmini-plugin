#!/usr/bin/env bash
# Idempotent installer/updater for LiSP + apc_mini_cart plugin on
# Raspberry Pi OS Trixie (64-bit). Safe to re-run as the update mechanism.
#
# Target: Raspberry Pi OS Trixie (Debian 13) on arm64. Vanilla Debian Trixie
# on other architectures will also work — the apt package names are identical.
# Bookworm and older are NOT supported (different librtmidi soversion, older
# python3-pyqt5, and on Bookworm python3 < 3.10 in places).
#
# Usage:
#   bash install.sh
#
# Override-able via env vars:
#   LISP_DIR    install dir for Linux Show Player          (default: ~/lisp/linux-show-player)
#   LISP_REPO   LiSP git remote                            (default: upstream)
#   LISP_REF    branch / tag to track                      (default: develop)
#   PLUGIN_DIR  install dir for this plugin                (default: ~/lisp/apc-mini-cart)
#   PLUGIN_REPO plugin git remote                          (default: GitHub)
#   PLUGIN_REF  branch / tag to track                      (default: main)
#   SKIP_APT=1  skip system-package install (already done) (default: unset)
#   AUTOSTART=1 launch LiSP on login via labwc autostart   (default: unset)
#   AUTOLOGIN=1 boot straight to the desktop, no password  (default: unset)

set -euo pipefail

LISP_DIR="${LISP_DIR:-$HOME/lisp/linux-show-player}"
LISP_REPO="${LISP_REPO:-https://github.com/FrancescoCeruti/linux-show-player.git}"
LISP_REF="${LISP_REF:-develop}"
PLUGIN_DIR="${PLUGIN_DIR:-$HOME/lisp/apc-mini-cart}"
PLUGIN_REPO="${PLUGIN_REPO:-https://github.com/nvdhulst79/LiSP-APCmini-plugin.git}"
PLUGIN_REF="${PLUGIN_REF:-main}"

AUTOSTART="${AUTOSTART:-0}"
AUTOLOGIN="${AUTOLOGIN:-0}"

# Keep poetry non-interactive AND out of the system keyring. Running the
# installer from the Pi's desktop session (especially with desktop autologin,
# where the login keyring is never unlocked) otherwise makes poetry's keyring
# integration pop a blocking "unlock keyring" dialog mid-install.
# POETRY_NO_INTERACTION alone does NOT prevent that — the null keyring backend
# does. We only ever hit public PyPI, so no stored credentials are needed.
export POETRY_NO_INTERACTION=1
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring

PLUGIN_MODULE="apc_mini_cart"
SYMLINK_PATH="${LISP_DIR}/lisp/plugins/${PLUGIN_MODULE}"

LAUNCHER_PATH="${HOME}/.local/bin/lisp-apc"
DESKTOP_PATH="${HOME}/.local/share/applications/lisp-apc.desktop"

# --- helpers ---------------------------------------------------------------

c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
c_red()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }
step()    { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die()     { c_red "ERROR: $*"; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

clone_or_pull() {
    local repo="$1" ref="$2" dir="$3"
    if [[ -d "${dir}/.git" ]]; then
        echo "  updating ${dir}"
        git -C "${dir}" fetch --quiet origin "${ref}"
        # Hard-reset to the remote tip rather than a ff-only pull. These are
        # managed deployment checkouts, not dev trees, and the LiSP clone gets
        # a local patch below (PyQt5 pins stripped from pyproject.toml +
        # poetry.lock re-locked). A ff-only pull would refuse to overwrite that
        # local change; reset --hard guarantees a pristine tree so the patch
        # re-applies cleanly on every update.
        git -C "${dir}" checkout --quiet "${ref}" 2>/dev/null \
            || git -C "${dir}" checkout --quiet -b "${ref}" --track "origin/${ref}"
        git -C "${dir}" reset --quiet --hard "origin/${ref}"
    else
        echo "  cloning ${repo} -> ${dir}"
        mkdir -p "$(dirname "${dir}")"
        git clone --quiet --branch "${ref}" "${repo}" "${dir}"
    fi
}

# --- preflight -------------------------------------------------------------

step "Preflight"

# Target Debian Trixie (Raspberry Pi OS Trixie). Older releases have a
# different librtmidi soversion (librtmidi6 instead of librtmidi7) and may
# not ship python3-pyqt5 5.15.11, so the apt step would either fail or
# install a wrong-version PyQt5 that doesn't satisfy LiSP's pin.
if [[ ! -f /etc/os-release ]]; then
    die "Cannot detect OS — /etc/os-release missing"
fi
# shellcheck disable=SC1091
. /etc/os-release
if [[ "${VERSION_CODENAME:-}" != "trixie" ]]; then
    die "This installer targets Debian Trixie (Raspberry Pi OS Trixie). Detected: ${PRETTY_NAME:-unknown}"
fi
if [[ -f /etc/rpi-issue ]]; then
    echo "  Raspberry Pi OS Trixie detected"
else
    c_yellow "  Trixie detected but not Raspberry Pi OS — apt list is tuned for RPi but should still work on plain Debian."
fi

require_cmd git
require_cmd curl

# Trixie ships python3 3.13 by default, so we don't gate on the version here —
# if python3 is missing entirely something is very wrong with the install.
require_cmd python3

# --- system packages -------------------------------------------------------

step "System packages"

APT_PACKAGES=(
    python3 python3-dev python3-poetry
    # C/C++ toolchain + pkg-config. PyGObject, pycairo and python-rtmidi have
    # no aarch64 wheels on PyPI, so poetry builds them from source on the Pi.
    # (meson/ninja are provided by pip's build isolation, so they're not needed
    # as system packages — but the compiler and pkg-config must be.)
    build-essential pkg-config
    # PyQt5 from apt — on Trixie this is 5.15.11, which satisfies LiSP's
    # `^5.15.2` pin. There is NO aarch64 wheel for `pyqt5` or `pyqt5-qt5` on
    # PyPI (and `pyqt5-qt5` is prebuilt Qt with no buildable sdist), so letting
    # poetry install them hard-fails on a Pi. The LiSP-repo step below strips
    # those two pins from pyproject and re-locks; system-site-packages (also
    # set there) makes this apt PyQt5 visible inside the venv, and it ships the
    # PyQt5.sip module too. qtsvg is a separate sub-package LiSP needs for icons.
    python3-pyqt5
    python3-pyqt5.qtsvg
    gstreamer1.0-plugins-good
    gstreamer1.0-plugins-ugly
    gstreamer1.0-plugins-bad
    gstreamer1.0-libav
    # GObject-introspection typelibs. PyGObject is only the bridge; the actual
    # `gi.repository` namespaces load from these .typelib files at runtime.
    # Without gir1.2-gstreamer-1.0 / -gst-plugins-base-1.0, LiSP's gst_backend
    # can't `import Gst`, throws on load, and silently disables itself (no
    # audio — the GUI still starts because that's PyQt5, not gi). These are NOT
    # pulled in by the gstreamer1.0-plugins-* packages above.
    gir1.2-glib-2.0
    gir1.2-gstreamer-1.0
    gir1.2-gst-plugins-base-1.0
    libasound2 libasound2-dev
    # PyGObject build dep. On Trixie, PyGObject 3.50+ uses meson and requires
    # `girepository-2.0` (girepository was merged into glib upstream), provided
    # by libgirepository-2.0-dev — NOT the old libgirepository1.0-dev, which no
    # longer satisfies the build. libcairo2-dev is for the pycairo build.
    libgirepository-2.0-dev libcairo2-dev
    # rtmidi runtime — Trixie bumped the soname from 6 to 7 (upstream still
    # rtmidi 6.0.0; Debian just changed the package name). On Bookworm this
    # would be librtmidi6.
    librtmidi7
    git
)

if [[ "${SKIP_APT:-0}" == "1" ]]; then
    c_yellow "  SKIP_APT=1 set, skipping apt install"
else
    if ! command -v apt-get >/dev/null 2>&1; then
        c_yellow "  apt-get not found, skipping (install equivalents manually)"
    else
        echo "  installing: ${APT_PACKAGES[*]}"
        sudo apt-get update -qq
        sudo apt-get install -y --no-install-recommends "${APT_PACKAGES[@]}"
    fi
fi

# --- poetry ----------------------------------------------------------------

step "Poetry"

if ! command -v poetry >/dev/null 2>&1; then
    die "poetry not on PATH after apt install. Install manually: https://python-poetry.org/docs/#installation"
fi
echo "  $(poetry --version)"

# --- LiSP repo -------------------------------------------------------------

step "Linux Show Player (${LISP_REF})"
clone_or_pull "${LISP_REPO}" "${LISP_REF}" "${LISP_DIR}"

# Tell poetry's venv to inherit Debian's system site-packages so the apt-
# installed python3-pyqt5 is visible inside the LiSP venv. Must be set BEFORE
# the venv is created — poetry only honours it at venv-creation time. --local
# scopes the setting to LiSP's repo via a poetry.toml file there, leaving your
# global poetry config untouched.
echo "  configuring poetry venv to inherit system site-packages (system PyQt5)"
( cd "${LISP_DIR}" && poetry config virtualenvs.options.system-site-packages true --local )

# Strip the PyQt5 pins and re-lock. PyQt5 has NO aarch64 wheels on PyPI —
# neither `pyqt5` nor `pyqt5-qt5` (the latter is prebuilt Qt with no buildable
# sdist) — so on a Pi `poetry install` can never satisfy them and aborts.
# system-site-packages alone is not enough: it makes the apt PyQt5 importable
# at runtime, but poetry still tries to fetch the locked PyPI PyQt5 packages.
# Removing the two top-level pins drops pyqt5 / pyqt5-qt5 / pyqt5-sip from the
# lock; the apt python3-pyqt5 (with its bundled PyQt5.sip) then provides PyQt5
# via system-site-packages. Harmless on x86_64 (those wheels exist there) and
# keeps both arches on one code path. clone_or_pull reset the tree to pristine
# above, so this edit is freshly re-applied on every run.
LISP_PYPROJECT="${LISP_DIR}/pyproject.toml"
if grep -qE '^pyqt5(-qt5)? = ' "${LISP_PYPROJECT}"; then
    echo "  removing PyQt5 PyPI pins (provided by apt python3-pyqt5) and re-locking"
    sed -i -E '/^pyqt5(-qt5)? = /d' "${LISP_PYPROJECT}"
    # Re-lock, preserving every other pin. poetry 1.x needs `--no-update` for
    # that; poetry 2.x removed the flag and preserves versions by default.
    # Probe the help text for the flag so we run the right command instead of
    # emitting a confusing 'The option "--no-update" does not exist' error.
    LOCK_CMD=(poetry lock)
    if ( cd "${LISP_DIR}" && poetry lock --help 2>/dev/null | grep -q -- '--no-update' ); then
        LOCK_CMD=(poetry lock --no-update)
    fi
    ( cd "${LISP_DIR}" && "${LOCK_CMD[@]}" ) \
        || die "poetry lock failed after stripping PyQt5 pins"
fi

# No --quiet: a silent failure here (a missing system build dep, an
# unresolvable wheel) is near-impossible to diagnose on a remote show machine.
# Let poetry's output through so the failing package is visible.
echo "  resolving Python deps (poetry install)"
( cd "${LISP_DIR}" && poetry install )

# --- plugin repo -----------------------------------------------------------

step "apc_mini_cart plugin (${PLUGIN_REF})"
clone_or_pull "${PLUGIN_REPO}" "${PLUGIN_REF}" "${PLUGIN_DIR}"

# --- symlink plugin into LiSP ----------------------------------------------

step "Wiring plugin into LiSP"
# The plugin package lives at the repo root (the repo *is* the package), so the
# symlink target is the clone directory itself.
PLUGIN_SRC="${PLUGIN_DIR}"
[[ -f "${PLUGIN_SRC}/__init__.py" ]] || die "expected plugin package at ${PLUGIN_SRC} (no __init__.py)"

if [[ -L "${SYMLINK_PATH}" ]]; then
    CURRENT_TARGET=$(readlink "${SYMLINK_PATH}")
    if [[ "${CURRENT_TARGET}" == "${PLUGIN_SRC}" ]]; then
        echo "  symlink already correct"
    else
        echo "  replacing stale symlink (was -> ${CURRENT_TARGET})"
        rm "${SYMLINK_PATH}"
        ln -s "${PLUGIN_SRC}" "${SYMLINK_PATH}"
    fi
elif [[ -e "${SYMLINK_PATH}" ]]; then
    die "${SYMLINK_PATH} exists and is not a symlink. Remove it and re-run."
else
    echo "  creating symlink: ${SYMLINK_PATH} -> ${PLUGIN_SRC}"
    ln -s "${PLUGIN_SRC}" "${SYMLINK_PATH}"
fi

# --- launcher --------------------------------------------------------------

step "Launcher"
mkdir -p "$(dirname "${LAUNCHER_PATH}")"
cat > "${LAUNCHER_PATH}" <<EOF
#!/usr/bin/env bash
# Auto-generated by lisp-apc-mini-cart installer.
exec poetry --directory "${LISP_DIR}" run linux-show-player "\$@"
EOF
chmod +x "${LAUNCHER_PATH}"
echo "  wrote ${LAUNCHER_PATH}"

mkdir -p "$(dirname "${DESKTOP_PATH}")"
cat > "${DESKTOP_PATH}" <<EOF
[Desktop Entry]
Type=Application
Name=Linux Show Player (APC)
Comment=Linux Show Player with APC mini mk2 cart-grid integration
Exec=${LAUNCHER_PATH} %f
Icon=linuxshowplayer
Terminal=false
Categories=AudioVideo;Audio;
MimeType=application/x-linuxshowplayer;
EOF
echo "  wrote ${DESKTOP_PATH}"

if ! echo "${PATH}" | tr ':' '\n' | grep -qx "${HOME}/.local/bin"; then
    c_yellow "  NOTE: ${HOME}/.local/bin is not on PATH. Add it to your shell rc, or run via the desktop entry."
fi

# --- autostart (optional) --------------------------------------------------

step "Autostart"

LABWC_AUTOSTART="${HOME}/.config/labwc/autostart"

if [[ "${AUTOSTART}" == "1" ]]; then
    # RPi OS Trixie's desktop compositor is labwc (Wayland). Two things we
    # confirmed on real hardware:
    #   * labwc does NOT honour ~/.config/autostart/*.desktop here — the
    #     lxsession-xdg-autostart line in /etc/xdg/labwc/autostart is vestigial
    #     under labwc, so an XDG autostart entry never fires.
    #   * this labwc runs BOTH /etc/xdg/labwc/autostart AND the user's
    #     ~/.config/labwc/autostart. So the user file must contain ONLY our
    #     launch line — copying the system lines (wf-panel-pi, pcmanfm-pi,
    #     kanshi) into it spawns a second panel/taskbar.
    # Hence: append just the launcher line, once, leaving any pre-existing user
    # autostart content untouched.
    mkdir -p "$(dirname "${LABWC_AUTOSTART}")"
    touch "${LABWC_AUTOSTART}"
    if grep -qF "${LAUNCHER_PATH}" "${LABWC_AUTOSTART}"; then
        echo "  labwc autostart already launches LiSP"
    else
        echo "${LAUNCHER_PATH} &" >> "${LABWC_AUTOSTART}"
        echo "  added LiSP launch to ${LABWC_AUTOSTART}"
    fi
    c_yellow "  (Assumes the labwc desktop. On a different compositor this file is"
    c_yellow "   ignored — LiSP just won't autostart; nothing else breaks.)"
else
    echo "  skipped (set AUTOSTART=1 to launch LiSP on login)"
fi

if [[ "${AUTOLOGIN}" == "1" ]]; then
    if command -v raspi-config >/dev/null 2>&1; then
        echo "  enabling desktop autologin (raspi-config)"
        sudo raspi-config nonint do_boot_behaviour B4 \
            || c_yellow "  autologin setup failed — enable it manually via raspi-config"
    else
        c_yellow "  AUTOLOGIN=1 set but raspi-config not found — skipping"
    fi
fi

# --- done ------------------------------------------------------------------

step "Done"
c_green "Install/update succeeded."
echo ""
echo "Launch:    lisp-apc           (or from the application menu)"
echo "Update:    re-run this script (git pull + poetry install)"
echo "Autostart: re-run with AUTOSTART=1 (launch on login) / AUTOLOGIN=1 (boot to desktop)"
echo "Logs:      ~/.local/share/LinuxShowPlayer/0.6/logs/lisp.log"
echo ""
echo "Reminder: in LiSP, set MIDI input/output to 'APC mini mk2 Control'"
echo "          (not 'APC mini mk2 Notes')."
