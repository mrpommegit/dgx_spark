import json
import os
import shlex
from pathlib import Path
from typing import Any

import docker
from docker.errors import NotFound
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


CONTAINER_NAME = os.getenv("LLAMACPP_CONTAINER_NAME", "llamacpp-runtime")
LLM_DIR = Path("/models")
NETWORK = os.getenv("DOCKER_NETWORK", "llamacpp-net")

app = FastAPI(title="llama.cpp Manager")
templates = Jinja2Templates(directory="/app/app/templates")
client = docker.from_env()


def env_default(name: str, fallback: str) -> str:
    return os.getenv(name, fallback)


DEFAULTS = {
    "image": env_default("LLAMACPP_IMAGE", "ghcr.io/ggerganov/llama.cpp:server-latest"),
    "ctx_size": env_default("LLAMACPP_CTX_SIZE", "8192"),
    "gpu_layers": env_default("LLAMACPP_GPU_LAYERS", "999"),
    "threads": env_default("LLAMACPP_THREADS", "8"),
    "parallel": env_default("LLAMACPP_PARALLEL", "1"),
    "batch_size": env_default("LLAMACPP_BATCH_SIZE", "2048"),
    "ubatch_size": env_default("LLAMACPP_UBATCH_SIZE", "512"),
    "extra_args": env_default("LLAMACPP_EXTRA_ARGS", ""),
}


def model_path(model: str) -> Path:
    root = LLM_DIR.resolve()
    path = (LLM_DIR / model).resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid model path")
    return path


def local_models() -> list[str]:
    """Find all model directories containing GGUF files."""
    if not LLM_DIR.exists():
        return []

    models: set[str] = set()
    for gguf in sorted(LLM_DIR.rglob("*.gguf")):
        relative_path = gguf.relative_to(LLM_DIR)
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        # Get the parent directory as the model path
        model_path = relative_path.parent.as_posix() or "."
        models.add(model_path)
    return sorted(models)


def get_gguf_files(model_path_str: str) -> list[str]:
    """Get all GGUF files in a model directory."""
    path = model_path(model_path_str)
    if not path.exists():
        return []
    return sorted([f.name for f in path.glob("*.gguf")])


def load_model_settings(model: str) -> dict[str, Any]:
    settings_path = model_path(model) / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        return {}


def write_model_settings(model: str, settings: dict[str, Any]) -> None:
    settings_path = model_path(model) / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, sort_keys=False) + "\n")


def model_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for model in local_models():
        settings = load_model_settings(model)
        profiles = settings.get("profiles", {})
        default_profile = settings.get("default_profile") or next(iter(profiles), "custom")
        gguf_files = get_gguf_files(model)
        catalog.append(
            {
                "path": model,
                "gguf_files": gguf_files,
                "default_profile": default_profile,
                "defaults": settings.get("llamacpp_defaults", {}),
                "profiles": profiles,
                "notes": settings.get("notes", []),
                "hf_repo": settings.get("hf_repo", ""),
            }
        )
    return catalog


def current_container() -> Any | None:
    try:
        return client.containers.get(CONTAINER_NAME)
    except NotFound:
        return None


def container_state() -> dict[str, Any]:
    container = current_container()
    if not container:
        return {"running": False, "status": "not created"}

    container.reload()
    labels = container.labels or {}
    return {
        "running": container.status == "running",
        "status": container.status,
        "model": labels.get("llamacpp-manager.model", ""),
        "gguf_file": labels.get("llamacpp-manager.gguf_file", ""),
        "profile": labels.get("llamacpp-manager.profile", ""),
        "ctx_size": labels.get("llamacpp-manager.ctx_size", ""),
        "gpu_layers": labels.get("llamacpp-manager.gpu_layers", ""),
        "threads": labels.get("llamacpp-manager.threads", ""),
        "parallel": labels.get("llamacpp-manager.parallel", ""),
        "batch_size": labels.get("llamacpp-manager.batch_size", ""),
        "ubatch_size": labels.get("llamacpp-manager.ubatch_size", ""),
        "extra_args": labels.get("llamacpp-manager.extra_args", ""),
    }


def stop_existing() -> None:
    container = current_container()
    if not container:
        return
    if container.status == "running":
        container.stop(timeout=30)
    container.remove()


def build_command(settings: dict[str, str]) -> list[str]:
    """Build llama-server command line arguments."""
    model_path = f"/models/{settings['model']}/{settings['gguf_file']}"

    command = [
        "--model", model_path,
        "--host", "0.0.0.0",
        "--port", "8080",
        "--ctx-size", settings["ctx_size"],
        "--n-gpu-layers", settings["gpu_layers"],
        "--threads", settings["threads"],
        "--parallel", settings["parallel"],
        "--batch-size", settings["batch_size"],
        "--ubatch-size", settings["ubatch_size"],
        "--jinja",  # Enable jinja templates for chat
        "--metrics",  # Enable metrics endpoint
        "--slots",  # Enable slots monitoring
    ]

    if settings["extra_args"]:
        command.extend(shlex.split(settings["extra_args"]))
    return command


def validate_runtime_settings(
    ctx_size: str,
    gpu_layers: str,
    threads: str,
    parallel: str,
    batch_size: str,
    ubatch_size: str,
) -> None:
    try:
        ctx_value = int(ctx_size)
        gpu_value = int(gpu_layers)
        threads_value = int(threads)
        parallel_value = int(parallel)
        batch_value = int(batch_size)
        ubatch_value = int(ubatch_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Numeric settings are invalid") from exc

    if ctx_value < 512:
        raise HTTPException(status_code=400, detail="Context size must be at least 512")
    if threads_value < 1 or threads_value > 64:
        raise HTTPException(status_code=400, detail="Threads must be between 1 and 64")
    if parallel_value < 1 or parallel_value > 4:
        raise HTTPException(status_code=400, detail="Parallel must be between 1 and 4")
    if batch_value < 1 or ubatch_value < 1:
        raise HTTPException(status_code=400, detail="Batch sizes must be at least 1")


def page_values(state: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    selected_model = state.get("model") or (catalog[0]["path"] if catalog else "")
    selected_settings = load_model_settings(selected_model) if selected_model else {}
    selected_profile = state.get("profile") or selected_settings.get("default_profile", "")
    selected_profile_values = selected_settings.get("profiles", {}).get(selected_profile, {})
    values = DEFAULTS | selected_settings.get("llamacpp_defaults", {}) | selected_profile_values
    if state.get("running"):
        values |= {key: value for key, value in state.items() if value}
    if selected_model:
        values["model"] = selected_model
    if selected_profile:
        values["profile"] = selected_profile
    if state.get("gguf_file"):
        values["gguf_file"] = state["gguf_file"]
    elif selected_model and (gguf_files := get_gguf_files(selected_model)):
        values["gguf_file"] = gguf_files[0]
    values.setdefault("image", DEFAULTS["image"])
    return values


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    state = container_state()
    catalog = model_catalog()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "models": [item["path"] for item in catalog],
            "catalog": catalog,
            "state": state,
            "values": page_values(state, catalog),
            "container_name": CONTAINER_NAME,
        },
    )


@app.post("/start")
def start(
    model: str = Form(...),
    gguf_file: str = Form(...),
    image: str = Form(...),
    ctx_size: str = Form(...),
    gpu_layers: str = Form(...),
    threads: str = Form(...),
    parallel: str = Form(...),
    batch_size: str = Form(...),
    ubatch_size: str = Form(...),
    profile: str = Form("custom"),
    extra_args: str = Form(""),
) -> RedirectResponse:
    if model not in local_models():
        raise HTTPException(status_code=400, detail="Selected model is not present in /models")

    gguf_files = get_gguf_files(model)
    if gguf_file not in gguf_files:
        raise HTTPException(status_code=400, detail="Selected GGUF file not found in model directory")

    validate_runtime_settings(ctx_size, gpu_layers, threads, parallel, batch_size, ubatch_size)

    host_llm_dir = os.getenv("LLM_DIR", "")
    if not host_llm_dir:
        raise HTTPException(status_code=500, detail="LLM_DIR is not set")

    settings = {
        "model": model,
        "gguf_file": gguf_file,
        "image": image,
        "ctx_size": ctx_size,
        "gpu_layers": gpu_layers,
        "threads": threads,
        "parallel": parallel,
        "batch_size": batch_size,
        "ubatch_size": ubatch_size,
        "profile": profile,
        "extra_args": extra_args.strip(),
    }

    stop_existing()

    # Create the runtime container
    client.containers.run(
        image=settings["image"],
        command=build_command(settings),
        name=CONTAINER_NAME,
        detach=True,
        remove=False,
        network=NETWORK,
        device_requests=[docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])],
        volumes={host_llm_dir: {"bind": "/models", "mode": "ro"}},
        labels={f"llamacpp-manager.{key}": value for key, value in settings.items()},
        ipc_mode="host",
    )
    return RedirectResponse("/", status_code=303)


@app.post("/profiles/save")
def save_profile(
    model: str = Form(...),
    profile_name: str = Form(...),
    gguf_file: str = Form(...),
    image: str = Form(...),
    ctx_size: str = Form(...),
    gpu_layers: str = Form(...),
    threads: str = Form(...),
    parallel: str = Form(...),
    batch_size: str = Form(...),
    ubatch_size: str = Form(...),
    extra_args: str = Form(""),
) -> RedirectResponse:
    if model not in local_models():
        raise HTTPException(status_code=400, detail="Selected model is not present in /models")
    validate_runtime_settings(ctx_size, gpu_layers, threads, parallel, batch_size, ubatch_size)

    cleaned_name = profile_name.strip().lower().replace(" ", "_")
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-"
    if not cleaned_name or any(char not in allowed for char in cleaned_name):
        raise HTTPException(status_code=400, detail="Profile name must use letters, numbers, dash, or underscore")

    settings = load_model_settings(model) or {
        "schema_version": 1,
        "model_path": model,
        "profiles": {},
    }
    settings.setdefault("profiles", {})[cleaned_name] = {
        "image": image,
        "gguf_file": gguf_file,
        "ctx_size": int(ctx_size),
        "gpu_layers": int(gpu_layers),
        "threads": int(threads),
        "parallel": int(parallel),
        "batch_size": int(batch_size),
        "ubatch_size": int(ubatch_size),
        "extra_args": extra_args.strip(),
    }
    settings["default_profile"] = cleaned_name
    settings["llamacpp_defaults"] = settings["profiles"][cleaned_name]
    write_model_settings(model, settings)
    return RedirectResponse("/", status_code=303)


@app.post("/stop")
def stop() -> RedirectResponse:
    stop_existing()
    return RedirectResponse("/", status_code=303)


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request) -> HTMLResponse:
    container = current_container()
    content = "llama.cpp container is not created."
    if container:
        content = container.logs(tail=300).decode("utf-8", errors="replace")
    return templates.TemplateResponse("logs.html", {"request": request, "logs": content})
