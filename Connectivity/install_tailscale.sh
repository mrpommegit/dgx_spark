#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing required command: $name" >&2
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

install_tailscale() {
  if command -v tailscale >/dev/null 2>&1; then
    echo "Tailscale is already installed."
    return
  fi

  require_command curl
  echo "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | as_root sh
}

configure_tailscaled() {
  if command -v systemctl >/dev/null 2>&1; then
    echo "Enabling tailscaled..."
    as_root systemctl enable --now tailscaled
  else
    echo "systemctl not found; skipping service enablement."
  fi
}

build_up_args() {
  local args=()

  if [[ -n "${TAILSCALE_AUTH_KEY:-}" ]]; then
    args+=("--auth-key=${TAILSCALE_AUTH_KEY}")
  fi

  if [[ -n "${TAILSCALE_HOSTNAME:-}" ]]; then
    args+=("--hostname=${TAILSCALE_HOSTNAME}")
  fi

  if [[ "${TAILSCALE_ACCEPT_ROUTES:-false}" == "true" ]]; then
    args+=("--accept-routes")
  fi

  if [[ "${TAILSCALE_SSH:-false}" == "true" ]]; then
    args+=("--ssh")
  fi

  if [[ "${TAILSCALE_ADVERTISE_EXIT_NODE:-false}" == "true" ]]; then
    args+=("--advertise-exit-node")
  fi

  if [[ -n "${TAILSCALE_ADVERTISE_ROUTES:-}" ]]; then
    args+=("--advertise-routes=${TAILSCALE_ADVERTISE_ROUTES}")
  fi

  if [[ -n "${TAILSCALE_ADVERTISE_TAGS:-}" ]]; then
    args+=("--advertise-tags=${TAILSCALE_ADVERTISE_TAGS}")
  fi

  if [[ -n "${TAILSCALE_EXTRA_ARGS:-}" ]]; then
    # shellcheck disable=SC2206
    args+=(${TAILSCALE_EXTRA_ARGS})
  fi

  printf '%s
' "${args[@]}"
}

configure_tailscale() {
  local up_args=()
  mapfile -t up_args < <(build_up_args)

  echo "Configuring Tailscale..."
  if [[ "${#up_args[@]}" -eq 0 ]]; then
    echo "No TAILSCALE_AUTH_KEY or options configured; starting interactive login."
  fi

  as_root tailscale up "${up_args[@]}"
  tailscale status || true
  tailscale ip || true
}

main() {
  install_tailscale
  configure_tailscaled
  configure_tailscale
}

main "$@"
