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
- LiteLLM Admin UI: `http://localhost:4000/ui/`

The default LiteLLM admin UI login from `.env.example` is `admin` / `change-me`.
Change `LITELLM_UI_USERNAME`, `LITELLM_UI_PASSWORD`, `LITELLM_MASTER_KEY`, and
`LITELLM_POSTGRES_PASSWORD` before exposing the stack beyond a trusted LAN/VPN.
The admin UI requires the bundled Postgres service because recent LiteLLM login
flows create UI session keys in the database.

In the manager, choose a local model and click `Apply and restart vLLM`.

## Langfuse Observability

LiteLLM is configured to send successful and failed proxy calls to Langfuse when
the `Docker/Langfuse` stack is running on the same Docker network:

```text
Open WebUI or API client -> LiteLLM -> vLLM/llama.cpp
                              |
                              v
                           Langfuse
```

Start this stack first, then start Langfuse:

```bash
cd ../Langfuse
cp .env.example .env
docker compose up -d
```

Langfuse will be available at `http://localhost:3001` and, on this host,
`http://100.99.111.1:3001` over Tailscale. Keep `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY` aligned between this stack's `.env` and
`Docker/Langfuse/.env`.

The Langfuse stack intentionally attaches to the same Docker network as LiteLLM
(`vllm-litellm_llmnet` by default). LiteLLM sends callback traffic to
`http://langfuse-web:3000`, so that hostname must resolve on the shared network.

## Open WebUI and LiteLLM Integration

Open WebUI is configured as an OpenAI-compatible client of LiteLLM:

```text
Open WebUI -> LiteLLM :4000/v1 -> vLLM runtime :8000/v1 -> local model
```

Open WebUI uses `OPENAI_API_BASE_URL=http://litellm:4000/v1` and
`OPENAI_API_KEY=${LITELLM_MASTER_KEY}`. LiteLLM exposes the `local-vllm` model
from `litellm/config.yaml` and forwards requests to `http://vllm-runtime:8000/v1`.
The `vllm-runtime` container is created dynamically by the manager UI, so start a
model there before expecting Open WebUI chats to complete.

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
