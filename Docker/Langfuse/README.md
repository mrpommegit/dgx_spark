# Langfuse Docker Stack

This stack runs Langfuse for LiteLLM observability and audit traces:

- `langfuse-web`: UI and API at `http://localhost:3001`
- `langfuse-worker`: ingestion worker
- `langfuse-postgres`: application database
- `langfuse-clickhouse`: trace/event analytics store
- `langfuse-redis`: queue backend
- `langfuse-minio`: local object storage

## Setup

Start `Docker/VLLM-LiteLLM` first so its Docker network exists:

```bash
cd ../VLLM-LiteLLM
docker compose up -d
```

Then configure and start Langfuse:

```bash
cd ../Langfuse
cp .env.example .env
docker compose up -d
```

Open:

- Langfuse: `http://localhost:3001`
- Langfuse over Tailscale on this host: `http://100.99.111.1:3001`
- MinIO API: `http://localhost:9090`
- MinIO console: `http://localhost:9091` bound to localhost only

The default bootstrap login from `.env.example` is
`admin@example.local` / `change-me`. Change all `change-me` values before
exposing the stack beyond a trusted LAN/VPN.

## LiteLLM Integration

LiteLLM is configured to send successful and failed proxy calls to Langfuse with:

```yaml
litellm_settings:
  success_callback: ["langfuse"]
  failure_callback: ["langfuse"]
```

The LiteLLM container uses:

```text
LANGFUSE_HOST=http://langfuse-web:3000
LANGFUSE_PUBLIC_KEY=pk-lf-local
LANGFUSE_SECRET_KEY=sk-lf-local
```

Keep these key values aligned with `Docker/Langfuse/.env`.

## Network Layout

All Langfuse services attach to the external LiteLLM network configured by
`LITELLM_DOCKER_NETWORK` in `.env` (`vllm-litellm_llmnet` by default). This is
intentional: LiteLLM resolves `langfuse-web` on that network and sends callback
traffic to `http://langfuse-web:3000`.

Do not attach `langfuse-web` to an additional default network unless you also
verify both the published host port and LiteLLM callback path. With multiple
Docker network IPs, Docker DNS can resolve `langfuse-web` to an address where the
Langfuse web process is not reachable, causing callbacks to fail while the UI
still appears healthy.

## Validation

After deployment, verify both paths:

```bash
curl http://localhost:3001/api/public/health
docker exec litellm-proxy python -c "import urllib.request; print(urllib.request.urlopen('http://langfuse-web:3000/api/public/health', timeout=10).read().decode())"
```

A successful LiteLLM callback appears in Langfuse as a trace named
`litellm-acompletion` in the `local-litellm` project.

## Resource Notes

ClickHouse is the component most likely to grow with trace volume. If this host
starts running memory-heavy models, add Docker memory limits to
`langfuse-clickhouse` and `langfuse-worker` before increasing audit traffic.
