#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${COMFYUI_DATA_DIR:-${SCRIPT_DIR}/data}"
HF_REVISION="${HF_REVISION:-main}"
HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
CURL_RETRIES="${CURL_RETRIES:-5}"

usage() {
  cat <<'USAGE'
Usage: ./add_models.sh <command> [args]

Presets:
  list                  Show available model presets.
  wan22-5b              Wan 2.2 5B text/image-to-video, fp16 diffusion model.
  wan22-14b-t2v         Wan 2.2 14B text-to-video, fp8 high/low noise models.
  wan22-14b-i2v         Wan 2.2 14B image-to-video, fp8 high/low noise models.
  flux-dev-fp8          FLUX.1 dev single-file fp8 checkpoint.
  flux-schnell-fp8      FLUX.1 schnell single-file fp8 checkpoint.
  sd15                  Stable Diffusion 1.5 checkpoint.

Generic Hugging Face download:
  hf <repo> <path-in-repo> <comfy-model-folder> [output-name]

Examples:
  ./add_models.sh wan22-5b
  HF_TOKEN=hf_xxx ./add_models.sh flux-dev-fp8
  ./add_models.sh hf Comfy-Org/flux1-dev flux1-dev-fp8.safetensors checkpoints
  ./add_models.sh hf some/repo model.safetensors diffusion_models renamed.safetensors

Environment:
  COMFYUI_DATA_DIR      Defaults to ./data beside this script.
  HF_TOKEN              Optional Hugging Face token for gated/private repos.
  HF_REVISION           Defaults to main.
USAGE
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
    "${DATA_DIR}/input" \
    "${DATA_DIR}/output"
}

list_presets() {
  cat <<'PRESETS'
Available presets:
  wan22-5b          ~18 GB: text encoder fp8, Wan 2.2 VAE, 5B TI2V fp16 model.
  wan22-14b-t2v     ~36 GB: text encoder fp8, Wan 2.1 VAE, 14B T2V high/low fp8 models.
  wan22-14b-i2v     ~36 GB: text encoder fp8, Wan 2.1 VAE, 14B I2V high/low fp8 models.
  flux-dev-fp8      ~17 GB: easy single-file checkpoint for FLUX.1 dev.
  flux-schnell-fp8  ~17 GB: easy single-file checkpoint for FLUX.1 schnell.
  sd15              ~4 GB: Stable Diffusion 1.5 checkpoint.
PRESETS
}

urlencode_path() {
  local value="$1"
  value="${value//%/%25}"
  value="${value// /%20}"
  value="${value//#/%23}"
  value="${value//?/%3F}"
  echo "${value}"
}

download_hf() {
  local repo="$1"
  local repo_path="$2"
  local comfy_folder="$3"
  local output_name="${4:-$(basename "${repo_path}")}"
  local encoded_path target tmp url

  prepare_dirs
  encoded_path="$(urlencode_path "${repo_path}")"
  target="${DATA_DIR}/models/${comfy_folder}/${output_name}"
  tmp="${target}.part"
  url="${HF_ENDPOINT}/${repo}/resolve/${HF_REVISION}/${encoded_path}"

  mkdir -p "$(dirname "${target}")"

  if [[ -s "${target}" ]]; then
    echo "Already exists: ${target}"
    return
  fi

  echo "Downloading ${repo}/${repo_path}"
  echo "  -> ${target}"

  local auth_args=()
  if [[ -n "${HF_TOKEN:-}" ]]; then
    auth_args=(-H "Authorization: Bearer ${HF_TOKEN}")
  fi

  curl -L --fail --retry "${CURL_RETRIES}" --retry-delay 5 --continue-at - \
    "${auth_args[@]}" \
    -o "${tmp}" \
    "${url}"
  mv "${tmp}" "${target}"
}

preset_wan22_5b() {
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors text_encoders
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan2.2_vae.safetensors vae
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors diffusion_models
}

preset_wan22_14b_t2v() {
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors text_encoders
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan_2.1_vae.safetensors vae
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors diffusion_models
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors diffusion_models
}

preset_wan22_14b_i2v() {
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors text_encoders
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan_2.1_vae.safetensors vae
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors diffusion_models
  download_hf Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors diffusion_models
}

command="${1:-}"
case "${command}" in
  list) list_presets ;;
  wan22-5b) preset_wan22_5b ;;
  wan22-14b-t2v) preset_wan22_14b_t2v ;;
  wan22-14b-i2v) preset_wan22_14b_i2v ;;
  flux-dev-fp8) download_hf Comfy-Org/flux1-dev flux1-dev-fp8.safetensors checkpoints ;;
  flux-schnell-fp8) download_hf Comfy-Org/flux1-schnell flux1-schnell-fp8.safetensors checkpoints ;;
  sd15) download_hf runwayml/stable-diffusion-v1-5 v1-5-pruned-emaonly.safetensors checkpoints ;;
  hf)
    if [[ $# -lt 4 || $# -gt 5 ]]; then
      usage >&2
      exit 1
    fi
    download_hf "$2" "$3" "$4" "${5:-$(basename "$3")}" 
    ;;
  -h|--help|help|"") usage ;;
  *)
    echo "Unknown model preset: ${command}" >&2
    usage >&2
    exit 1
    ;;
esac
