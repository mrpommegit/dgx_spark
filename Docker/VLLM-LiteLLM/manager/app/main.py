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


CONTAINER_NAME = os.getenv("VLLM_CONTAINER_NAME", "vllm-runtime")
LLM_DIR = Path("/models")
NETWORK = os.getenv("DOCKER_NETWORK", "vllm-litellm_llmnet")

app = FastAPI(title="vLLM Manager")
templates = Jinja2Templates(directory="/app/app/templates")
client = docker.from_env()


def env_default(name: str, fallback: str) -> str:
    return os.getenv(name, fallback)


DEFAULTS = {
    "image": env_default("VLLM_IMAGE", "vllm/vllm-openai:latest"),
    "gpu_memory_utilization": env_default("VLLM_GPU_MEMORY_UTILIZATION", "0.70"),
    "max_model_len": env_default("VLLM_MAX_MODEL_LEN", "8192"),
    "max_num_seqs": env_default("VLLM_MAX_NUM_SEQS", "16"),
    "dtype": env_default("VLLM_DTYPE", "auto"),
    "tensor_parallel_size": env_default("VLLM_TENSOR_PARALLEL_SIZE", "1"),
    "quantization": env_default("VLLM_QUANTIZATION", ""),
    "extra_args": env_default("VLLM_EXTRA_ARGS", ""),
}


def model_path(model: str) -> Path:
    root = LLM_DIR.resolve()
    path = (LLM_DIR / model).resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid model path")
    return path


def local_models() -> list[str]:
    if not LLM_DIR.exists():
        return []

    models: set[str] = set()
    for config in sorted(LLM_DIR.rglob("config.json")):
        relative_path = config.parent.relative_to(LLM_DIR)
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        models.add(relative_path.as_posix())
    for settings in sorted(LLM_DIR.rglob("settings.json")):
        if settings.parent == LLM_DIR:
            continue
        relative_path = settings.parent.relative_to(LLM_DIR)
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        models.add(relative_path.as_posix())
    return sorted(models)


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
        catalog.append(
            {
                "path": model,
                "has_config": (model_path(model) / "config.json").exists(),
                "hf_repo": settings.get("hf_repo", ""),
                "default_profile": default_profile,
                "defaults": settings.get("vllm_defaults", {}),
                "profiles": profiles,
                "notes": settings.get("notes", []),
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
        "model": labels.get("vllm-manager.model", ""),
        "profile": labels.get("vllm-manager.profile", ""),
        "gpu_memory_utilization": labels.get("vllm-manager.gpu_memory_utilization", ""),
        "max_model_len": labels.get("vllm-manager.max_model_len", ""),
        "max_num_seqs": labels.get("vllm-manager.max_num_seqs", ""),
        "dtype": labels.get("vllm-manager.dtype", ""),
        "tensor_parallel_size": labels.get("vllm-manager.tensor_parallel_size", ""),
        "quantization": labels.get("vllm-manager.quantization", ""),
        "extra_args": labels.get("vllm-manager.extra_args", ""),
    }


def stop_existing() -> None:
    container = current_container()
    if not container:
        return
    if container.status == "running":
        container.stop(timeout=30)
    container.remove()


def build_command(settings: dict[str, str]) -> list[str]:
    command = [
        f"/models/{settings['model']}",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--gpu-memory-utilization",
        settings["gpu_memory_utilization"],
        "--max-model-len",
        settings["max_model_len"],
        "--max-num-seqs",
        settings["max_num_seqs"],
        "--dtype",
        settings["dtype"],
        "--tensor-parallel-size",
        settings["tensor_parallel_size"],
    ]
    if settings["quantization"]:
        command.extend(["--quantization", settings["quantization"]])
    if "--served-model-name" not in settings["extra_args"]:
        command.extend(["--served-model-name", "local-vllm"])
    if settings["extra_args"]:
        command.extend(shlex.split(settings["extra_args"]))
    return command


def validate_runtime_settings(
    gpu_memory_utilization: str,
    max_model_len: str,
    max_num_seqs: str,
    tensor_parallel_size: str,
) -> None:
    try:
        gpu_value = float(gpu_memory_utilization)
        max_len_value = int(max_model_len)
        max_seqs_value = int(max_num_seqs)
        tensor_parallel_value = int(tensor_parallel_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Numeric settings are invalid") from exc

    if not 0.05 <= gpu_value <= 0.98:
        raise HTTPException(status_code=400, detail="GPU memory utilization must be between 0.05 and 0.98")
    if max_len_value < 512 or max_seqs_value < 1 or tensor_parallel_value < 1:
        raise HTTPException(status_code=400, detail="Context, sequence, and tensor parallel settings are invalid")


def page_values(state: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    selected_model = state.get("model") or (catalog[0]["path"] if catalog else "")
    selected_settings = load_model_settings(selected_model) if selected_model else {}
    selected_profile = state.get("profile") or selected_settings.get("default_profile", "")
    selected_profile_values = selected_settings.get("profiles", {}).get(selected_profile, {})
    values = DEFAULTS | selected_settings.get("vllm_defaults", {}) | selected_profile_values
    if state.get("running"):
        values |= {key: value for key, value in state.items() if value}
    if selected_model:
        values["model"] = selected_model
    if selected_profile:
        values["profile"] = selected_profile
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
    image: str = Form(...),
    gpu_memory_utilization: str = Form(...),
    max_model_len: str = Form(...),
    max_num_seqs: str = Form(...),
    dtype: str = Form(...),
    tensor_parallel_size: str = Form(...),
    profile: str = Form("custom"),
    quantization: str = Form(""),
    extra_args: str = Form(""),
) -> RedirectResponse:
    if model not in local_models():
        raise HTTPException(status_code=400, detail="Selected model is not present in /models")
    if not (model_path(model) / "config.json").exists():
        raise HTTPException(status_code=400, detail="Selected model does not have config.json yet")
    validate_runtime_settings(gpu_memory_utilization, max_model_len, max_num_seqs, tensor_parallel_size)

    host_llm_dir = os.getenv("LLM_DIR", "")
    if not host_llm_dir:
        raise HTTPException(status_code=500, detail="LLM_DIR is not set")

    settings = {
        "model": model,
        "image": image,
        "gpu_memory_utilization": gpu_memory_utilization,
        "max_model_len": max_model_len,
        "max_num_seqs": max_num_seqs,
        "dtype": dtype,
        "tensor_parallel_size": tensor_parallel_size,
        "profile": profile,
        "quantization": quantization.strip(),
        "extra_args": extra_args.strip(),
    }

    stop_existing()
    client.containers.run(
        image=settings["image"],
        command=build_command(settings),
        name=CONTAINER_NAME,
        detach=True,
        remove=False,
        network=NETWORK,
        device_requests=[docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])],
        volumes={host_llm_dir: {"bind": "/models", "mode": "ro"}},
        labels={f"vllm-manager.{key}": value for key, value in settings.items()},
        shm_size="2g",
        ipc_mode="host",
    )
    return RedirectResponse("/", status_code=303)


@app.post("/profiles/save")
def save_profile(
    model: str = Form(...),
    profile_name: str = Form(...),
    image: str = Form(...),
    gpu_memory_utilization: str = Form(...),
    max_model_len: str = Form(...),
    max_num_seqs: str = Form(...),
    dtype: str = Form(...),
    tensor_parallel_size: str = Form(...),
    quantization: str = Form(""),
    extra_args: str = Form(""),
) -> RedirectResponse:
    if model not in local_models():
        raise HTTPException(status_code=400, detail="Selected model is not present in /models")
    validate_runtime_settings(gpu_memory_utilization, max_model_len, max_num_seqs, tensor_parallel_size)

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
        "dtype": dtype,
        "gpu_memory_utilization": float(gpu_memory_utilization),
        "max_model_len": int(max_model_len),
        "max_num_seqs": int(max_num_seqs),
        "tensor_parallel_size": int(tensor_parallel_size),
        "quantization": quantization.strip(),
        "extra_args": extra_args.strip(),
    }
    settings["default_profile"] = cleaned_name
    settings["vllm_defaults"] = settings["profiles"][cleaned_name]
    write_model_settings(model, settings)
    return RedirectResponse("/", status_code=303)


@app.post("/stop")
def stop() -> RedirectResponse:
    stop_existing()
    return RedirectResponse("/", status_code=303)


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request) -> HTMLResponse:
    container = current_container()
    content = "vLLM container is not created."
    if container:
        content = container.logs(tail=300).decode("utf-8", errors="replace")
    return templates.TemplateResponse("logs.html", {"request": request, "logs": content})
