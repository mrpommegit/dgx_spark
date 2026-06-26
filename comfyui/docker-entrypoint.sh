#!/usr/bin/env bash
set -euo pipefail

mkdir -p /opt/ComfyUI/models /opt/ComfyUI/input /opt/ComfyUI/output /opt/ComfyUI/custom_nodes

if [[ -n "${COMFYUI_CUSTOM_NODE_REPOS:-}" ]]; then
  for repo in ${COMFYUI_CUSTOM_NODE_REPOS}; do
    name="$(basename "${repo}" .git)"
    target="/opt/ComfyUI/custom_nodes/${name}"
    if [[ ! -d "${target}/.git" ]]; then
      git clone --depth 1 "${repo}" "${target}"
    fi
    if [[ -f "${target}/requirements.txt" ]]; then
      python -m pip install -r "${target}/requirements.txt"
    fi
  done
fi

exec "$@"
