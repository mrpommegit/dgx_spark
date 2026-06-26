# ComfyUI on DGX Spark

This directory provides a Docker-first ComfyUI setup for image and video
generation workflows on DGX Spark. It follows the same basic shape as NVIDIA's
Spark ComfyUI reference: ComfyUI, CUDA PyTorch, `--listen 0.0.0.0`, and port
`8188`.

## Recommendation

Use Docker unless you have a specific reason to install directly on the host.
With NVIDIA Container Toolkit and `gpus: all`, PyTorch talks to the GPU through
the host driver and the performance cost is normally negligible. The big win is
maintenance: ComfyUI code and Python packages live in the image, while models,
custom nodes, inputs, and outputs stay in bind-mounted host folders.

Use the host install only if Docker GPU passthrough is not available, a custom
node requires unusual system integration, or you need to exactly reproduce a
non-container NVIDIA support recipe.

## Docker setup

From this directory:

```bash
./install_comfyui.sh docker
./install_comfyui.sh download-sd15
./install_comfyui.sh start
```

Open `http://localhost:8188`.

The installer creates `./data` by default:

- `data/models` - checkpoints, VAEs, LoRAs, diffusion/video models.
- `data/custom_nodes` - ComfyUI Manager and video helper nodes.
- `data/input` - uploaded media.
- `data/output` - generated images and videos.

Edit `comfyui/.env` after the first run to change ports, data location, PyTorch
wheel index, ComfyUI branch/ref, or custom node repositories.

## Host setup

```bash
./install_comfyui.sh host
```

Then run the command printed by the script. The host install uses the same
`./data` model, input, and output directories. Host custom nodes are installed
under `./host/ComfyUI/custom_nodes`.

## Video generation notes

The Compose file installs `ComfyUI-VideoHelperSuite` by default because most
video workflows need video load/save nodes. Actual video generation still
depends on the model family you choose. Put large video model checkpoints under
the matching directory in `data/models`, usually `diffusion_models`,
`checkpoints`, `vae`, or a custom-node-specific folder documented by that node.

## Useful commands

```bash
./install_comfyui.sh logs
./install_comfyui.sh stop
docker compose --env-file .env -f docker-compose.yml pull
docker compose --env-file .env -f docker-compose.yml build --no-cache
```

## Adding models

Use `add_models.sh` to place model files in the ComfyUI folders mounted by
Docker:

```bash
./add_models.sh list
./add_models.sh wan22-5b
./add_models.sh wan22-14b-t2v
./add_models.sh wan22-14b-i2v
./add_models.sh flux-dev-fp8
./add_models.sh flux-schnell-fp8
```

Some Hugging Face repositories are gated or require accepting a license. For
those, accept the model license in your Hugging Face account and run with a
token:

```bash
HF_TOKEN=hf_xxx ./add_models.sh flux-dev-fp8
```

For models not covered by presets, use the generic downloader:

```bash
./add_models.sh hf owner/repo path/in/repo.safetensors diffusion_models
```

Wan 2.2 presets install text encoders, VAEs, and diffusion models from
`Comfy-Org/Wan_2.2_ComfyUI_Repackaged`. FLUX presets install easy single-file
FP8 checkpoints into `models/checkpoints`.
