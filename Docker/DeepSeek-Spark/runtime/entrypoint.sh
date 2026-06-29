#!/usr/bin/env bash
set -euo pipefail

MODEL_REPO=${MODEL_REPO:?Set MODEL_REPO}
MODEL_REVISION=${MODEL_REVISION:?Set MODEL_REVISION}
SERVED_MODEL_NAME=${SERVED_MODEL_NAME:-DeepSeek-V4-Flash-Spark}
PORT=${PORT:-8000}
HF_HOME=${HF_HOME:-/models/hf-cache}
MODEL_DIR=${MODEL_DIR:-}

if [[ -z "$MODEL_DIR" ]]; then
  MODEL_DIR="${HF_HOME}/models--${MODEL_REPO//\//--}/snapshots/${MODEL_REVISION}"
fi

if [[ ! -d "$MODEL_DIR" ]]; then
  echo "Missing model snapshot: $MODEL_DIR" >&2
  echo "Download ${MODEL_REPO}@${MODEL_REVISION} into HF_HOME=$HF_HOME or set MODEL_DIR." >&2
  exit 1
fi

python3 /opt/deepseek-spark/patch_vllm_reap_gb10.py

args=(
  vllm serve "$MODEL_DIR"
  --served-model-name "$SERVED_MODEL_NAME"
  --host 0.0.0.0
  --port "$PORT"
  --trust-remote-code
  --tensor-parallel-size 1
  --pipeline-parallel-size 1
  --kv-cache-dtype "${KV_CACHE_DTYPE:-fp8}"
  --kv-cache-memory-bytes "${KV_CACHE_MEMORY_BYTES:-6G}"
  --block-size 256
  --max-model-len "${CONTEXT_LENGTH:-200000}"
  --max-num-seqs "${MAX_NUM_SEQS:-1}"
  --max-num-batched-tokens "${MAX_NUM_BATCHED_TOKENS:-4096}"
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.88}"
  --distributed-executor-backend mp
  --tokenizer-mode deepseek_v4
  --load-format safetensors
  --disable-uvicorn-access-log
  --enable-prefix-caching
  --tool-call-parser deepseek_v4
  --enable-auto-tool-choice
  --reasoning-parser deepseek_v4
  --reasoning-config '{"reasoning_parser":"deepseek_v4","reasoning_start_str":"<think>","reasoning_end_str":"</think>"}'
  --default-chat-template-kwargs "{\"thinking\":${THINKING:-true}}"
)

if [[ "${ENFORCE_EAGER:-0}" == "1" ]]; then
  args+=(--enforce-eager)
else
  args+=(--compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE","custom_ops":["all"]}')
fi

if [[ -n "${SPECULATIVE_CONFIG:-}" ]]; then
  args+=(--speculative-config "$SPECULATIVE_CONFIG")
fi

if [[ -n "${EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  extra_args_array=($EXTRA_ARGS)
  args+=("${extra_args_array[@]}")
fi

exec "${args[@]}"
