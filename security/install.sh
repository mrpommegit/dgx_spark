#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_SCRIPT="${SCRIPT_DIR}/dgx_spark_network_mode.py"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
INSTALL_PATH="${INSTALL_PATH:-${INSTALL_DIR}/dgx-spark-network-mode}"
DESKTOP_USER="${DESKTOP_USER:-${SUDO_USER:-${USER}}}"

usage() {
  cat <<'USAGE'
Usage: ./install.sh [command]

Commands:
  install     Install dependencies, command, and tray autostart entry.
  uninstall   Remove the installed command and tray autostart entry.

Default command: install

Environment:
  INSTALL_DIR=/usr/local/bin
  INSTALL_PATH=/usr/local/bin/dgx-spark-network-mode
  DESKTOP_USER=<current user>
USAGE
}

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    require_command sudo
    sudo "$@"
  fi
}

desktop_home() {
  local home
  home="$(getent passwd "${DESKTOP_USER}" | cut -d: -f6 || true)"
  if [[ -z "${home}" ]]; then
    echo "Could not determine home directory for DESKTOP_USER=${DESKTOP_USER}" >&2
    exit 1
  fi
  printf '%s\n' "${home}"
}

install_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get not found; skipping package installation."
    return
  fi

  require_command apt-cache

  local packages=(
    nftables
    python3-gi
    gir1.2-gtk-3.0
  )

  if apt-cache show pkexec >/dev/null 2>&1; then
    packages+=(pkexec)
  elif apt-cache show policykit-1 >/dev/null 2>&1; then
    packages+=(policykit-1)
  fi

  if apt-cache show gir1.2-ayatanaappindicator3-0.1 >/dev/null 2>&1; then
    packages+=(gir1.2-ayatanaappindicator3-0.1)
  elif apt-cache show gir1.2-appindicator3-0.1 >/dev/null 2>&1; then
    packages+=(gir1.2-appindicator3-0.1)
  else
    echo "No AppIndicator GIR package found in apt; tray support may be missing." >&2
  fi

  echo "Installing network mode tray dependencies..."
  as_root apt-get update
  as_root apt-get install -y "${packages[@]}"
}

install_command() {
  if [[ ! -f "${SOURCE_SCRIPT}" ]]; then
    echo "Source script not found: ${SOURCE_SCRIPT}" >&2
    exit 1
  fi

  echo "Installing ${INSTALL_PATH}..."
  as_root install -d -m 0755 "${INSTALL_DIR}"
  as_root install -m 0755 "${SOURCE_SCRIPT}" "${INSTALL_PATH}"
}

install_autostart() {
  local home autostart_dir desktop_file
  home="$(desktop_home)"
  autostart_dir="${home}/.config/autostart"
  desktop_file="${autostart_dir}/dgx-spark-network-mode.desktop"

  echo "Installing tray autostart entry for ${DESKTOP_USER}..."
  install -d -m 0755 "${autostart_dir}"
  cat >"${desktop_file}" <<DESKTOP
[Desktop Entry]
Type=Application
Name=DGX Spark Network Mode
Exec=/usr/bin/env python3 ${INSTALL_PATH}
Icon=network-wireless
Terminal=false
X-GNOME-Autostart-enabled=true
DESKTOP

  if [[ "${EUID}" -eq 0 ]]; then
    chown "${DESKTOP_USER}:${DESKTOP_USER}" "${desktop_file}" "${autostart_dir}" || true
  fi
}

verify_install() {
  require_command python3
  python3 "${INSTALL_PATH}" --status >/dev/null

  if ! command -v pkexec >/dev/null 2>&1; then
    echo "Warning: pkexec was not found. Mode changes from the tray will not work." >&2
  fi

  if ! command -v nft >/dev/null 2>&1; then
    echo "Warning: nft was not found. Firewall mode changes will not work." >&2
  fi
}

uninstall() {
  local home desktop_file
  home="$(desktop_home)"
  desktop_file="${home}/.config/autostart/dgx-spark-network-mode.desktop"

  echo "Removing tray autostart entry..."
  rm -f "${desktop_file}"

  echo "Removing installed command..."
  as_root rm -f "${INSTALL_PATH}"
}

main() {
  local command="${1:-install}"

  case "${command}" in
    install)
      install_packages
      install_command
      install_autostart
      verify_install
      cat <<READY
DGX Spark Network Mode is installed.

Start it now with:
  ${INSTALL_PATH}

It will also start automatically at the next desktop login.
READY
      ;;
    uninstall)
      uninstall
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
