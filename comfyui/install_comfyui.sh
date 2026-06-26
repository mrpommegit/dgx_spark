#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"
DATA_DIR="${COMFYUI_DATA_DIR:-${SCRIPT_DIR}/data}"
PORT="${COMFYUI_PORT:-8188}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/cu130}"
CUSTOM_NODE_REPOS="${COMFYUI_CUSTOM_NODE_REPOS:-https://github.com/ltdrdata/ComfyUI-Manager.git https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git}"

usage() {
  cat <<'USAGE'
Usage: ./install_comfyui.sh [command]

Commands:
  docker          Prepare data folders, write .env if needed, build the image.
  start           Start ComfyUI with Docker Compose.
  stop            Stop the Docker Compose service.
  logs            Follow ComfyUI logs.
  download-sd15   Download the Stable Diffusion 1.5 checkpoint into models/checkpoints.
  host            Install ComfyUI directly on the host under ./host/ComfyUI.

Default command: docker
USAGE
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/docker-compose.yml" "$@"
}

prepare_dirs() {
  mkdir -p \
    "${DATA_DIR}/models/checkpoints" \
    "${DATA_DIR}/models/clip_vision" \
    "${DATA_DIR}/models/controlnet" \
    "${DATA_DIR}/models/diffusion_models" \
    "${DATA_DIR}/models/loras" \
    "${DATA_DIR}/models/style_models" \
    "${DATA_DIR}/models/text_encoders" \
    "${DATA_DIR}/models/unet" \
    "${DATA_DIR}/models/vae" \
    "${DATA_DIR}/custom_nodes" \
    "${DATA_DIR}/input" \
    "${DATA_DIR}/output"
}

write_env() {
  if [[ -f "${ENV_FILE}" ]]; then
    return
  fi

  cat >"${ENV_FILE}" <<ENV
COMFYUI_DATA_DIR=${DATA_DIR}
COMFYUI_PORT=${PORT}
COMFYUI_REF=master
COMFYUI_IMAGE=dgx-spark-comfyui:local
COMFYUI_CONTAINER_NAME=comfyui
COMFYUI_SHM_SIZE=16gb
PYTORCH_INDEX_URL=${PYTORCH_INDEX_URL}
COMFYUI_ARGS=--listen 0.0.0.0 --port 8188 --enable-manager
COMFYUI_EXTRA_ARGS=
COMFYUI_CUSTOM_NODE_REPOS=${CUSTOM_NODE_REPOS}
ENV
}

check_docker_gpu() {
  require_cmd docker
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is required. Install the Docker compose plugin first." >&2
    exit 1
  fi

  if ! docker info --format '{{json .Runtimes}}' | grep -q nvidia; then
    cat >&2 <<'NVIDIA_RUNTIME'
Docker does not report the NVIDIA runtime.
Install/configure NVIDIA Container Toolkit, then rerun:
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
NVIDIA_RUNTIME
    exit 1
  fi
}

docker_install() {
  prepare_dirs
  write_env
  check_docker_gpu
  compose build
  cat <<READY
Docker image is built.
Start ComfyUI:
  cd ${SCRIPT_DIR}
  ./install_comfyui.sh start

Open:
  http://localhost:${PORT}
READY
}

download_sd15() {
  require_cmd curl
  prepare_dirs
  local target="${DATA_DIR}/models/checkpoints/v1-5-pruned-emaonly.safetensors"
  if [[ -f "${target}" ]]; then
    echo "Checkpoint already exists: ${target}"
    return
  fi
  curl -L \
    -o "${target}" \
    "https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors"
}

install_custom_nodes_host() {
  local custom_nodes_dir="$1"
  mkdir -p "${custom_nodes_dir}"

  for repo in ${CUSTOM_NODE_REPOS}; do
    local name target
    name="$(basename "${repo}" .git)"
    target="${custom_nodes_dir}/${name}"
    if [[ ! -d "${target}/.git" ]]; then
      git clone --depth 1 "${repo}" "${target}"
    fi
    if [[ -f "${target}/requirements.txt" ]]; then
      python -m pip install -r "${target}/requirements.txt"
    fi
  done
}

write_extra_model_paths() {
  local host_dir="$1"
  cat >"${host_dir}/extra_model_paths.yaml" <<MODEL_PATHS
dgx_spark_data:
  base_path: ${DATA_DIR}/models
  checkpoints: checkpoints
  clip_vision: clip_vision
  controlnet: controlnet
  diffusion_models: diffusion_models
  loras: loras
  style_models: style_models
  text_encoders: text_encoders
  unet: unet
  vae: vae
MODEL_PATHS
}

host_install() {
  require_cmd git
  require_cmd python3
  prepare_dirs

  local host_dir="${SCRIPT_DIR}/host/ComfyUI"
  if [[ ! -d "${host_dir}/.git" ]]; then
    mkdir -p "${SCRIPT_DIR}/host"
    git clone https://github.com/comfyanonymous/ComfyUI.git "${host_dir}"
  fi

  python3 -m venv "${host_dir}/.venv"
  # shellcheck source=/dev/null
  source "${host_dir}/.venv/bin/activate"
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install --index-url "${PYTORCH_INDEX_URL}" torch torchvision torchaudio
  python -m pip install -r "${host_dir}/requirements.txt"
  install_custom_nodes_host "${host_dir}/custom_nodes"
  write_extra_model_paths "${host_dir}"

  cat <<READY
Host install is ready.
Start ComfyUI:
  cd ${host_dir}
  source .venv/bin/activate
  python main.py --listen 0.0.0.0 --port 8188 --enable-manager --input-directory ${DATA_DIR}/input --output-directory ${DATA_DIR}/output
READY
}

command="${1:-docker}"
case "${command}" in
  docker) docker_install ;;
  start)
    prepare_dirs
    write_env
    check_docker_gpu
    compose up -d
    echo "ComfyUI is starting at http://localhost:${PORT}"
    ;;
  stop)
    require_cmd docker
    compose down
    ;;
  logs)
    require_cmd docker
    compose logs -f
    ;;
  download-sd15) download_sd15 ;;
  host) host_install ;;
  -h|--help|help) usage ;;
  *)
    usage >&2
    exit 1
    ;;
esac
