# llama.cpp Stack

GGUF model inference stack for DGX Spark with llama.cpp server, manager UI, and LiteLLM integration.

## Start

```bash
cd Docker/LlamaCPP
cp .env.example .env
docker compose up -d --build
```

Open the manager UI at:

```text
http://localhost:8089/
```

## Services

- **llama.cpp Manager** (port 8089) - Web UI for managing GGUF models
- **llama.cpp Runtime** (port 8081) - OpenAI-compatible API server
- **llama.cpp WebUI** (port 8082) - Built-in chat interface from llama.cpp

## Model Storage

GGUF models are stored in `~/LLMs/` by default. The manager scans for `*.gguf` files
and allows you to select and configure them.

Download GGUF models:

```bash
# Example: Using Hugging Face CLI
pip install huggingface_hub
huggingface-cli download unsloth/Qwen3.6-35B-A3B-MTP-GGUF UD-Q4_K_XL/Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL-*.gguf --local-dir ~/LLMs/unsloth/Qwen3.6-35B-A3B-MTP-GGUF:UD-Q4_K_XL
```

## LiteLLM Integration

Add llama.cpp as a backend in your LiteLLM `config.yaml`:

```yaml
model_list:
  - model_name: local-llamacpp
    litellm_params:
      api_base: http://llamacpp-runtime:8080/v1
      mode: openai
```

Then Open WebUI can select between:
- `local-vllm` - vLLM runtime (for HuggingFace models)
- `local-llamacpp` - llama.cpp runtime (for GGUF models)

## Portal Integration

All services appear in the DGX Spark Portal at `http://<box-ip>/`:
- llama.cpp Manager (settings icon)
- llama.cpp Runtime (CPU icon)

## Troubleshooting

- If the manager shows "No GGUF files found", ensure models are in `~/LLMs/`
- For memory issues, reduce `LLAMACPP_CTX_SIZE` or increase GPU offloading
- Check logs: `docker logs llamacpp-runtime`
