# DGX Spark Operations Notes

This folder is used to maintain DGX Spark best practices, configuration notes,
fine-tuning guidance, and proposed stack decisions.

## Scope

- Best practices for running and maintaining DGX Spark systems.
- Configuration scripts and repeatable setup procedures.
- Fine-tuning notes, experiments, and operational recommendations.
- Stack proposals for security, networking, tooling, observability, and model
  workflows.

## Current Contents

- `security/dgx_spark_network_mode.py` - Ubuntu tray indicator for switching
  DGX Spark network/privacy modes using `nftables`.
- `Wifi_alwaysON.sh` - NetworkManager helper to keep a configured Wi-Fi
  connection enabled and reconnecting.
- `Connectivity/install_tailscale.sh` - Tailscale installer/configuration
  helper driven by `.env`.
- `comfyui/` - Docker-first ComfyUI setup for image and video generation on
  DGX Spark, with a host install fallback.
- `Docker/VLLM-LiteLLM/` - Docker Compose stack for vLLM, LiteLLM, Open WebUI,
  and a small manager UI for switching local models and runtime settings.
- `Docker/LlamaCPP/` - GGUF model inference stack with llama.cpp server, manager UI,
  and LiteLLM integration for CPU/GPU hybrid inference.
- `Docker/portal-proxy/` - Dynamic portal on port 80 that lists running
  containerized web apps published with `portal.*` labels.
- `Docker/Portainer/` - Portainer container management UI with persistent
  data under `~/portainer-data`.
- `security/` - Security-related scripts and configuration proposals.
- `finetuning/` - Fine-tuning support scripts, notes, and workflow proposals.

## Suggested Structure

Use these folders to keep future work easy to review:

- `security/` - Firewalling, privacy modes, access controls, hardening, and
  threat-model notes.
- `Connectivity/` - VPN, overlay networking, remote access, and connectivity
  automation.
- `finetuning/` - Fine-tuning recipes, dataset preparation notes, training
  configuration, evaluation plans, and experiment results.
- `configs/` - Reusable system, service, network, and tool configuration files.
- `proposals/` - Stack proposals, design decisions, tradeoffs, and rollout
  plans.
- `docs/` - General DGX Spark operating procedures and best-practice notes.

## Quick Starts

### Tailscale

Configure the Tailscale values in `.env`, then run:

```bash
./Connectivity/install_tailscale.sh
```

Leave `TAILSCALE_AUTH_KEY` empty for an interactive login, or set an auth key
for unattended provisioning. Optional settings in `.env.example` cover hostname,
route acceptance, Tailscale SSH, exit-node advertising, subnet routes, tags, and
extra `tailscale up` arguments.

### ComfyUI

From `comfyui/`:

```bash
./install_comfyui.sh docker
./install_comfyui.sh start
```

Open `http://localhost:8188`. Runtime data, custom nodes, downloaded models,
inputs, and outputs live under `comfyui/data/` by default and are intentionally
ignored by git.

### Dynamic Portal

From `Docker/portal-proxy/`:

```bash
docker compose up -d
```

Open `http://<box-ip>/`. The portal lists running containers that have
`portal.enable=true` labels and opens each app through its published host port.
Use `PORTAL_PORT=8080` in `Docker/portal-proxy/.env` if port 80 is already used.

### Portainer

From `Docker/Portainer/`:

```bash
cp .env.example .env
docker compose up -d
```

Open `https://<box-ip>:9443/`. Create an admin user on first visit. Persistent
data is stored in `~/portainer-data` by default.

### vLLM + LiteLLM + Open WebUI

From `Docker/VLLM-LiteLLM/`:

```bash
cp .env.example .env
docker compose up -d --build
```

Set `LLM_DIR` in `.env` to the host directory containing downloaded Hugging Face
models. The manager UI is exposed on `http://localhost:8088`, Open WebUI on
`http://localhost:3000`, and the LiteLLM OpenAI-compatible API on
`http://localhost:4000/v1`.

### llama.cpp + Manager UI

From `Docker/LlamaCPP/`:

```bash
cp .env.example .env
docker compose up -d --build
```

Open the manager UI at `http://localhost:8089/`. GGUF models are scanned from
`~/LLMs/` by default. The manager provides profile-based configuration for
context size, GPU offloading, threads, and other llama-server options. The
runtime provides an OpenAI-compatible API on port 8081 and integrates with
LiteLLM as the `local-llamacpp` backend.

Download GGUF models:

```bash
pip install huggingface_hub
huggingface-cli download unsloth/Qwen3.6-35B-A3B-MTP-GGUF \
  UD-Q4_K_XL/Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL-*.gguf \
  --local-dir ~/LLMs/unsloth/Qwen3.6-35B-A3B-MTP-GGUF:UD-Q4_K_XL
```

## Contribution Notes

- Prefer scripts that are idempotent and safe to rerun.
- Document prerequisites, target OS/version, required privileges, and rollback
  steps for any system-level change.
- Keep machine-specific values, credentials, and secrets out of committed files.
- Add a short note beside each proposal explaining the problem, recommendation,
  tradeoffs, and validation plan.
- For fine-tuning work, record model name, dataset source, hardware assumptions,
  hyperparameters, evaluation method, and observed results.

## Safety

Some scripts in this folder can change network or security behavior. Review them
before running, and test changes in a controlled environment before applying them
to a production DGX Spark system.
