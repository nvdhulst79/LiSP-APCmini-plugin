#!/usr/bin/env bash
# Idempotent installer/updater for LiSP + apc_mini_cart plugin on a
# Debian-family Linux box. Safe to re-run as the update mechanism.
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

if ! [[ -f /etc/os-release ]] || ! grep -qE 'ID(_LIKE)?=.*(debian|ubuntu)' /etc/os-release; then
    c_yellow "Not a Debian/Ubuntu/Mint system. Continuing, but apt step will be skipped."
    SKIP_APT=1
fi

require_cmd git
require_cmd curl

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
PY_MAJOR=${PY_VER%.*}; PY_MINOR=${PY_VER#*.}
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
    die "python3 >= 3.10 required (found ${PY_VER}). Install python3 from your distro first."
fi
echo "  python3 ${PY_VER} OK"

# --- system packages -------------------------------------------------------

step "System packages"

APT_PACKAGES=(
    python3 python3-dev python3-poetry
    gstreamer1.0-plugins-good
    gstreamer1.0-plugins-ugly
    gstreamer1.0-plugins-bad
    gstreamer1.0-libav
    libasound2 libasound2-dev
    libgirepository1.0-dev libcairo2-dev
    librtmidi6
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

echo "  resolving Python deps (poetry install)"
( cd "${LISP_DIR}" && poetry install --quiet )

# --- plugin repo -----------------------------------------------------------

step "apc_mini_cart plugin (${PLUGIN_REF})"
clone_or_pull "${PLUGIN_REPO}" "${PLUGIN_REF}" "${PLUGIN_DIR}"

# --- symlink plugin into LiSP ----------------------------------------------

step "Wiring plugin into LiSP"
PLUGIN_SRC="${PLUGIN_DIR}/${PLUGIN_MODULE}"
[[ -d "${PLUGIN_SRC}" ]] || die "expected plugin source at ${PLUGIN_SRC}"

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
