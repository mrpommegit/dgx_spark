# vLLM + LiteLLM Docker Stack

This stack runs:

- `vllm-runtime`: created, stopped, and recreated by the manager UI
- `litellm-proxy`: OpenAI-compatible proxy at `http://localhost:4000/v1`
- `open-webui`: chat UI at `http://localhost:3000`
- `vllm-manager`: settings UI at `http://localhost:8088`

## Setup

```bash
cp .env.example .env
```

Edit `.env` and set `LLM_DIR` to the folder that contains your already downloaded Hugging Face models, for example:

```bash
LLM_DIR=/home/your-user/LLMs
```

Start the stack:

```bash
docker compose up -d --build
```

The server needs Docker with NVIDIA Container Toolkit configured, because vLLM is started with GPU access.

Open:

- Manager UI: `http://localhost:8088`
- Open WebUI: `http://localhost:3000`
- LiteLLM API: `http://localhost:4000/v1`

In the manager, choose a local model and click `Apply and restart vLLM`.

## What Can Be Changed Dynamically

Generation parameters such as temperature, top-p, max output tokens, stop sequences, and penalties are request-level settings. Open WebUI, LiteLLM, or any OpenAI-compatible client can change them per request.

vLLM memory and model-load settings are process-level settings. Changing these requires restarting the vLLM runtime:

- model
- max context length, `--max-model-len`
- GPU memory cap, `--gpu-memory-utilization`
- tensor parallel size
- dtype
- quantization
- max concurrent sequences, `--max-num-seqs`

The manager UI handles this by recreating the `vllm-runtime` container.

## Memory Notes

vLLM intentionally reserves a GPU KV-cache based on `--gpu-memory-utilization`. It does not continuously return unused GPU memory to the system while the model is loaded. To keep it from taking all GPU memory, lower `VLLM_GPU_MEMORY_UTILIZATION` or set it in the manager UI.

For CPU RAM, the model files are mounted read-only from `LLM_DIR`. Docker can limit container RAM, but hard RAM limits can make model startup fail instead of gracefully shrinking. GPU memory is controlled mainly through vLLM arguments.

## Security Note

The manager container mounts `/var/run/docker.sock` so it can start and stop the vLLM container. This is powerful access to the host Docker daemon. Keep the manager bound to trusted networks only.
