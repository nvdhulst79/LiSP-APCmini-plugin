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
#   LISP_DIR    install dir for Linux Show Player          (default: ~/dev/linux-show-player)
#   LISP_REPO   LiSP git remote                            (default: upstream)
#   LISP_REF    branch / tag to track                      (default: develop)
#   PLUGIN_DIR  install dir for this plugin                (default: ~/dev/lisp-apc-mini-cart)
#   PLUGIN_REPO plugin git remote                          (default: GitHub)
#   PLUGIN_REF  branch / tag to track                      (default: main)
#   SKIP_APT=1  skip system-package install (already done) (default: unset)

set -euo pipefail

LISP_DIR="${LISP_DIR:-$HOME/dev/linux-show-player}"
LISP_REPO="${LISP_REPO:-https://github.com/FrancescoCeruti/linux-show-player.git}"
LISP_REF="${LISP_REF:-develop}"
PLUGIN_DIR="${PLUGIN_DIR:-$HOME/dev/lisp-apc-mini-cart}"
PLUGIN_REPO="${PLUGIN_REPO:-https://github.com/nvdhulst79/LiSP-APCmini-plugin.git}"
PLUGIN_REF="${PLUGIN_REF:-main}"

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
        git -C "${dir}" checkout --quiet "${ref}"
        git -C "${dir}" pull --quiet --ff-only origin "${ref}"
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
    # PyQt5 from apt — on Trixie this is exactly 5.15.11, which satisfies
    # LiSP's `^5.15.2` pin in pyproject.toml. We install it via apt (instead
    # of letting poetry pull it from PyPI) because there is no aarch64 wheel
    # for PyQt5 on PyPI, so on a Raspberry Pi the alternative is a 20–30 min
    # source build of PyQt5+sip against Qt5 dev headers. The companion
    # `poetry config virtualenvs.options.system-site-packages true --local`
    # call below makes the LiSP venv actually see this system package.
    # qtsvg is a separate Debian sub-package and is needed by LiSP for icons.
    python3-pyqt5
    python3-pyqt5.qtsvg
    gstreamer1.0-plugins-good
    gstreamer1.0-plugins-ugly
    gstreamer1.0-plugins-bad
    gstreamer1.0-libav
    libasound2 libasound2-dev
    libgirepository1.0-dev libcairo2-dev
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
# installed python3-pyqt5 is visible inside the LiSP venv. Without this the
# venv is fully isolated, poetry doesn't see PyQt5 5.15.11 from apt, and
# falls back to building PyQt5 from source (no aarch64 wheel on PyPI; see
# the apt list comment above). --local scopes the setting to LiSP's repo
# via a poetry.toml file there — your global poetry config is untouched.
echo "  configuring poetry venv to inherit system site-packages (system PyQt5)"
( cd "${LISP_DIR}" && poetry config virtualenvs.options.system-site-packages true --local )

echo "  resolving Python deps (poetry install)"
( cd "${LISP_DIR}" && poetry install --quiet )

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

# --- done ------------------------------------------------------------------

step "Done"
c_green "Install/update succeeded."
echo ""
echo "Launch:    lisp-apc           (or from the application menu)"
echo "Update:    re-run this script (git pull + poetry install)"
echo "Logs:      ~/.local/share/LinuxShowPlayer/0.6/logs/lisp.log"
echo ""
echo "Reminder: in LiSP, set MIDI input/output to 'APC mini mk2 Control'"
echo "          (not 'APC mini mk2 Notes')."
