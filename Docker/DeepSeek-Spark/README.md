# DeepSeek Spark vLLM Stack

Dedicated Docker Compose stack for the custom DeepSeek V4 Flash Spark runtime
from <https://github.com/0xSero/deepseek-spark>.

It uses the upstream custom image:

```text
ghcr.io/0xsero/deepseek-v4-flash-spark-vllm:cutlass451-g27
```

## Setup

```bash
cp .env.example .env
```

Set `DEEPSEEK_SPARK_HF_HOME` to the host Hugging Face cache that contains the
model snapshots.

For a single-node DGX Spark, use the Mini/K144 profile. It expects:

```text
models--0xSero--DeepSeek-V4-Flash-162B/snapshots/d663e8fb16809f6619000648b187b257249ed824
```

Start the Mini runtime:

```bash
docker compose --profile mini up -d deepseek-spark-mini-vllm
```

The larger K160/180B profile remains available for hosts that can support it.
It expects:

```text
models--0xSero--DeepSeek-V4-Flash-180B/snapshots/7c360e1cd4a5168099dbc54d16d929bf6df04990
```

Start the larger runtime:

```bash
docker compose up -d deepseek-spark-vllm
```

Stop the larger runtime before switching to Mini on the same node:

```bash
docker compose stop deepseek-spark-vllm
docker compose --profile mini up -d
```

The services attach to the existing `vllm-litellm_llmnet` Docker network, so
start `Docker/VLLM-LiteLLM` first. LiteLLM exposes a single clean Open WebUI
name:

- `deepseek-spark`

In the current default config, that alias routes to
`DeepSeek-V4-Flash-Spark-Mini` at `http://deepseek-spark-mini-vllm:8000/v1`.
Open WebUI reaches it through LiteLLM at `http://litellm:4000/v1`.
