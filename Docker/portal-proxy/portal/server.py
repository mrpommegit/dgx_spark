import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parent
HOST_ROOT = Path(os.getenv("PORTAL_HOST_ROOT", "/host"))
SOCKET_PATH = "/var/run/docker.sock"
PORT = int(os.getenv("PORTAL_INTERNAL_PORT", "8080"))
TITLE = os.getenv("PORTAL_TITLE", "DGX Spark Portal")
REFRESH_SECONDS = os.getenv("PORTAL_REFRESH_SECONDS", "5")
STATS_HISTORY_PATH = Path(os.getenv("PORTAL_STATS_HISTORY_PATH", "/tmp/dgx-portal-litellm-history.json"))
STATS_RETENTION_SECONDS = 7 * 24 * 60 * 60
STATS_SAMPLE_SECONDS = int(os.getenv("PORTAL_STATS_SAMPLE_SECONDS", "60"))
STATS_HISTORY_LOCK = threading.Lock()

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def decode_chunked(body: bytes) -> bytes:
    decoded = bytearray()
    index = 0
    while index < len(body):
        line_end = body.find(b"\r\n", index)
        if line_end == -1:
            break
        size_text = body[index:line_end].split(b";", 1)[0]
        size = int(size_text, 16)
        index = line_end + 2
        if size == 0:
            break
        decoded.extend(body[index:index + size])
        index += size + 2
    return bytes(decoded)


def decode_docker_multiplexed(body: bytes) -> bytes:
    decoded = bytearray()
    index = 0
    while index + 8 <= len(body):
        stream_type = body[index]
        if stream_type not in (1, 2) or body[index + 1:index + 4] != b"\x00\x00\x00":
            return body
        frame_size = int.from_bytes(body[index + 4:index + 8], "big")
        index += 8
        if index + frame_size > len(body):
            return body
        decoded.extend(body[index:index + frame_size])
        index += frame_size
    if index == len(body) and decoded:
        return bytes(decoded)
    return body


def docker_get(path: str, params: dict[str, str] | None = None) -> object:
    query = f"?{urlencode(params)}" if params else ""
    request = (
        f"GET {path}{query} HTTP/1.1\r\n"
        "Host: docker\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(SOCKET_PATH)
        sock.sendall(request)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)

    response = b"".join(chunks)
    header, _, body = response.partition(b"\r\n\r\n")
    status_line = header.splitlines()[0].decode("utf-8", errors="replace") if header else ""
    if " 200 " not in status_line:
        raise RuntimeError(status_line or "Docker API request failed")
    if b"transfer-encoding: chunked" in header.lower():
        body = decode_chunked(body)
    return json.loads(body.decode("utf-8"))


def request_origin(handler: BaseHTTPRequestHandler) -> tuple[str, str]:
    host = handler.headers.get("Host", "localhost").split(":", 1)[0]
    proto = handler.headers.get("X-Forwarded-Proto", "http")
    return proto, host


def app_url(labels: dict[str, str], ports: list[dict[str, object]], handler: BaseHTTPRequestHandler) -> str:
    explicit = labels.get("portal.url", "").strip()
    if explicit:
        return explicit

    proto, host = request_origin(handler)
    # Allow label to override protocol for HTTPS services
    label_proto = labels.get("portal.protocol", "").strip()
    if label_proto in ("http", "https"):
        proto = label_proto

    path = labels.get("portal.path", "").strip()
    if path:
        return f"{proto}://{handler.headers.get('Host', host)}{path}"

    label_port = labels.get("portal.port", "").strip()
    if label_port:
        return f"{proto}://{host}:{label_port}"

    for item in ports:
        public_port = item.get("PublicPort")
        if public_port:
            return f"{proto}://{host}:{public_port}"

    return ""


def first_public_port(ports: list[dict[str, object]]) -> str:
    for item in ports:
        public_port = item.get("PublicPort")
        if public_port:
            return str(public_port)
    return ""


def container_stats(container_id: str) -> dict[str, object]:
    try:
        stats = docker_get(f"/containers/{container_id}/stats", {"stream": "false"})
    except Exception:
        return {"cpu_percent": 0, "memory_percent": 0, "memory_used": 0, "memory_limit": 0, "block_io": 0}

    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})
    cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
    system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
    online_cpus = cpu_stats.get("online_cpus") or len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", []) or []) or 1
    cpu_percent_value = 0
    if cpu_delta > 0 and system_delta > 0:
        cpu_percent_value = round((cpu_delta / system_delta) * online_cpus * 100, 1)

    memory_stats = stats.get("memory_stats", {})
    memory_used = int(memory_stats.get("usage", 0) or 0)
    memory_limit = int(memory_stats.get("limit", 0) or 0)
    memory_percent_value = round((memory_used / memory_limit) * 100, 1) if memory_limit else 0

    block_io = 0
    for entry in stats.get("blkio_stats", {}).get("io_service_bytes_recursive", []) or []:
        block_io += int(entry.get("value", 0) or 0)

    return {
        "cpu_percent": cpu_percent_value,
        "memory_percent": memory_percent_value,
        "memory_used": memory_used,
        "memory_limit": memory_limit,
        "block_io": block_io,
    }


def portal_apps(handler: BaseHTTPRequestHandler) -> list[dict[str, object]]:
    containers = docker_get("/containers/json", {"all": "0"})
    apps: list[dict[str, object]] = []
    for container in containers:
        labels = container.get("Labels") or {}
        if labels.get("portal.enable", "false").lower() != "true":
            continue

        ports = container.get("Ports") or []
        name = labels.get("portal.name") or (container.get("Names") or [container.get("Id", "app")])[0].strip("/")
        try:
            order = int(labels.get("portal.order", "100"))
        except ValueError:
            order = 100

        apps.append(
            {
                "id": container.get("Id", "")[:12],
                "name": name,
                "description": labels.get("portal.description", ""),
                "url": app_url(labels, ports, handler),
                "port": labels.get("portal.port") or first_public_port(ports),
                "icon": labels.get("portal.icon", "app"),
                "status": container.get("State", "running"),
                "container": (container.get("Names") or [""])[0].strip("/"),
                "order": order,
                "stats": container_stats(container.get("Id", "")),
            }
        )

    return sorted(apps, key=lambda item: (item["order"], str(item["name"]).lower()))


def read_text(path: Path) -> str:
    return path.read_text(errors="replace").strip()


def meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in read_text(HOST_ROOT / "proc/meminfo").splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {"total": total, "used": max(total - available, 0), "percent": percent(max(total - available, 0), total)}


def cpu_times() -> list[int]:
    first = read_text(HOST_ROOT / "proc/stat").splitlines()[0].split()[1:]
    return [int(value) for value in first]


def cpu_percent() -> int:
    first = cpu_times()
    time.sleep(0.08)
    second = cpu_times()
    idle_delta = (second[3] + second[4]) - (first[3] + first[4])
    total_delta = sum(second) - sum(first)
    if total_delta <= 0:
        return 0
    return round((1 - idle_delta / total_delta) * 100)


def disk_usage() -> dict[str, int]:
    usage = shutil.disk_usage(HOST_ROOT)
    return {"total": usage.total, "used": usage.used, "percent": percent(usage.used, usage.total)}



def percent(used: int, total: int) -> int:
    if total <= 0:
        return 0
    return round((used / total) * 100)


def ip_addresses() -> list[dict[str, object]]:
    try:
        result = subprocess.run(
            ["ip", "-j", "addr", "show"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        data = json.loads(result.stdout)
    except Exception:
        return []

    rows: list[dict[str, object]] = []
    for iface in data:
        name = iface.get("ifname", "")
        if name == "lo" or name.startswith(("docker", "br-", "veth")):
            continue
        for addr in iface.get("addr_info", []):
            family = addr.get("family")
            local = addr.get("local")
            if family not in {"inet", "inet6"} or not local:
                continue
            rows.append(
                {
                    "interface": name,
                    "address": local,
                    "family": "IPv4" if family == "inet" else "IPv6",
                    "tailscale": name.startswith("tailscale") or local.startswith("100."),
                }
            )
    return rows


def tailscale_status(addresses: list[dict[str, object]]) -> dict[str, object]:
    up = any(row["tailscale"] for row in addresses)
    try:
        result = subprocess.run(["tailscale", "status", "--json"], check=True, capture_output=True, text=True, timeout=2)
        data = json.loads(result.stdout)
        up = bool(data.get("Self", {}).get("Online", up))
        return {"installed": True, "online": up, "hostname": data.get("Self", {}).get("HostName", "")}
    except Exception:
        return {"installed": False, "online": up, "hostname": ""}


def system_snapshot() -> dict[str, object]:
    addresses = ip_addresses()
    return {
        "metrics": {
            "ram": meminfo(),
            "cpu": {"percent": cpu_percent()},
            "disk": disk_usage(),
        },
        "network": {
            "tailscale": tailscale_status(addresses),
            "addresses": addresses,
        },
    }


def stats_range_seconds(range_name: str) -> int:
    ranges = {
        "hour": 60 * 60,
        "day": 24 * 60 * 60,
        "7days": STATS_RETENTION_SECONDS,
    }
    return ranges.get(range_name, ranges["hour"])


def read_stats_history() -> dict[str, dict[str, object]]:
    try:
        data = json.loads(STATS_HISTORY_PATH.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    history: dict[str, dict[str, object]] = {}
    for series_id, value in data.items():
        if not isinstance(series_id, str):
            continue
        if isinstance(value, list):
            continue
        if isinstance(value, dict):
            samples = value.get("samples", [])
            meta = value.get("meta", {})
            if isinstance(samples, list) and isinstance(meta, dict) and meta.get("engine_key") != "legacy":
                history[series_id] = {
                    "meta": meta,
                    "samples": [sample for sample in samples if isinstance(sample, dict)],
                }
    return history


def write_stats_history(history: dict[str, dict[str, object]]) -> None:
    STATS_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = STATS_HISTORY_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(history, separators=(",", ":")))
    temporary_path.replace(STATS_HISTORY_PATH)


def metric_value(model: dict[str, object], key: str) -> float:
    value = model.get(key, 0)
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0


def model_series_id(model: dict[str, object]) -> str:
    return str(model.get("series_id") or f'{model.get("engine_key", "engine")}:{model.get("model_name", "model")}')


def model_meta(model: dict[str, object]) -> dict[str, object]:
    return {
        "series_id": model_series_id(model),
        "model_name": str(model.get("model_name") or "Unknown Model"),
        "engine_key": str(model.get("engine_key") or "engine"),
        "engine_name": str(model.get("engine_name") or model.get("type") or "Engine"),
        "type": str(model.get("type") or "LLM"),
    }


def sample_from_model(model: dict[str, object], timestamp: int) -> dict[str, object]:
    return {
        "ts": timestamp,
        "tpp": metric_value(model, "prompt_tokens_per_second"),
        "tft": metric_value(model, "prompt_time_to_first_token"),
        "toks": metric_value(model, "tokens_per_second"),
    }


def record_stats_history(models: list[dict[str, object]], range_name: str) -> dict[str, dict[str, object]]:
    now = int(time.time())
    retention_cutoff = now - STATS_RETENTION_SECONDS
    range_cutoff = now - stats_range_seconds(range_name)

    with STATS_HISTORY_LOCK:
        history = read_stats_history()
        for model in models:
            series_id = model_series_id(model)
            entry = history.setdefault(series_id, {"meta": model_meta(model), "samples": []})
            entry["meta"] = model_meta(model)
            samples = entry.setdefault("samples", [])
            if isinstance(samples, list):
                samples.append(sample_from_model(model, now))

        cleaned: dict[str, dict[str, object]] = {}
        for series_id, entry in history.items():
            samples = entry.get("samples", [])
            if not isinstance(samples, list):
                continue
            recent_samples = [
                sample for sample in samples
                if int(sample.get("ts", 0) or 0) >= retention_cutoff
            ]
            if recent_samples:
                cleaned[series_id] = {"meta": entry.get("meta", {}), "samples": recent_samples}

        write_stats_history(cleaned)

    return {
        series_id: {
            "meta": entry.get("meta", {}),
            "samples": [
                sample for sample in entry.get("samples", [])
                if int(sample.get("ts", 0) or 0) >= range_cutoff
            ],
        }
        for series_id, entry in cleaned.items()
    }


def stats_with_history(range_name: str) -> dict[str, object]:
    payload = litellm_stats()
    models = payload.get("models", [])
    if not isinstance(models, list):
        models = []
    history = record_stats_history(models, range_name)

    by_series = {model_series_id(model): model for model in models if isinstance(model, dict)}
    for series_id, entry in history.items():
        meta = entry.get("meta", {}) if isinstance(entry.get("meta"), dict) else {}
        model = by_series.setdefault(
            series_id,
            {
                "series_id": series_id,
                "model_name": meta.get("model_name", series_id),
                "engine_key": meta.get("engine_key", "engine"),
                "engine_name": meta.get("engine_name", "Engine"),
                "type": meta.get("type", "LLM"),
            },
        )
        model["history"] = entry.get("samples", [])

    engines: dict[str, dict[str, object]] = {}
    for model in by_series.values():
        engine_key = str(model.get("engine_key") or "engine")
        engine = engines.setdefault(
            engine_key,
            {
                "engine_key": engine_key,
                "engine_name": str(model.get("engine_name") or model.get("type") or "Engine"),
                "type": str(model.get("type") or "LLM"),
                "models": [],
            },
        )
        engine["models"].append(model)

    return {"range": range_name, "engines": list(engines.values()), "models": list(by_series.values())}


def parse_prometheus_labels(label_text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    index = 0
    while index < len(label_text):
        equals = label_text.find("=", index)
        if equals == -1:
            break
        key = label_text[index:equals].strip().strip(",")
        index = equals + 1
        if index >= len(label_text) or label_text[index] != '"':
            break
        index += 1
        value_chars: list[str] = []
        while index < len(label_text):
            char = label_text[index]
            if char == '\\' and index + 1 < len(label_text):
                value_chars.append(label_text[index + 1])
                index += 2
                continue
            if char == '"':
                index += 1
                break
            value_chars.append(char)
            index += 1
        labels[key] = "".join(value_chars)
        comma = label_text.find(",", index)
        if comma == -1:
            break
        index = comma + 1
    return labels


def parse_prometheus_metric(line: str) -> tuple[str, dict[str, str], float] | None:
    try:
        metric_part, raw_value = line.rsplit(None, 1)
        value = float(raw_value)
    except ValueError:
        return None

    if "{" in metric_part and metric_part.endswith("}"):
        name, label_text = metric_part.split("{", 1)
        return name, parse_prometheus_labels(label_text[:-1]), value
    return metric_part, {}, value


def parse_model_from_command(container_name: str) -> str:
    try:
        inspect_data = docker_get(f"/containers/{container_name}/json")
        config = inspect_data.get("Config", {}) if isinstance(inspect_data, dict) else {}
        cmd = config.get("Cmd") or []
        if isinstance(cmd, list):
            for index, item in enumerate(cmd):
                if item == "--model" and index + 1 < len(cmd):
                    return Path(str(cmd[index + 1])).stem
                if str(item).startswith("--model="):
                    return Path(str(item).split("=", 1)[1]).stem
    except Exception:
        pass
    return "llama.cpp"


def litellm_stats() -> dict[str, object]:
    """Fetch model statistics from vLLM and llama.cpp runtimes via Docker exec API."""
    models: dict[str, dict[str, object]] = {}

    def docker_exec(container_name: str, cmd: list[str]) -> str:
        """Execute command in container via Docker socket."""
        try:
            # Create exec instance
            create_body = json.dumps({"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": cmd})
            create_req = (
                f"POST /containers/{container_name}/exec HTTP/1.1\r\n"
                f"Host: docker\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(create_body)}\r\n"
                f"Connection: close\r\n"
                "\r\n"
            ).encode("utf-8") + create_body.encode("utf-8")

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect(SOCKET_PATH)
                sock.sendall(create_req)

                # Read response
                response = b""
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    response += chunk

            header, _, body = response.partition(b"\r\n\r\n")
            if b"transfer-encoding: chunked" in header.lower():
                body = decode_chunked(body)

            create_result = json.loads(body.decode("utf-8"))
            exec_id = create_result.get("Id", "")
            if not exec_id:
                return ""

            # Start exec
            start_body = json.dumps({"Detach": False, "Tty": False})
            start_req = (
                f"POST /exec/{exec_id}/start HTTP/1.1\r\n"
                f"Host: docker\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(start_body)}\r\n"
                f"Connection: close\r\n"
                "\r\n"
            ).encode("utf-8") + start_body.encode("utf-8")

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(10)
                sock.connect(SOCKET_PATH)
                sock.sendall(start_req)

                response = b""
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    response += chunk

            header, _, body = response.partition(b"\r\n\r\n")
            if b"transfer-encoding: chunked" in header.lower():
                body = decode_chunked(body)

            body = decode_docker_multiplexed(body)
            return body.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def collect_vllm_metrics(container_name: str, engine_prefix: str, series_prefix: str) -> None:
        metrics_text = docker_exec(container_name, ["curl", "-s", "http://localhost:8000/metrics"])
        if not metrics_text:
            return

        by_model: dict[str, dict[str, object]] = {}
        for line in metrics_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = parse_prometheus_metric(line)
            if not parsed:
                continue
            name, labels, value = parsed
            model_name = labels.get("model_name")
            engine_id = labels.get("engine", "0")
            if not model_name:
                continue

            series_id = f"{series_prefix}:{engine_id}:{model_name}"
            item = by_model.setdefault(
                series_id,
                {
                    "series_id": series_id,
                    "engine_key": f"{series_prefix}:{engine_id}",
                    "engine_name": f"{engine_prefix} {engine_id}",
                    "model_name": model_name,
                    "type": "vllm",
                    "_prompt_tokens": 0.0,
                    "_generation_tokens": 0.0,
                    "_time_e2e_sum": 0.0,
                    "_time_queue_sum": 0.0,
                    "_request_count": 0.0,
                },
            )

            if name == "vllm:prompt_tokens_total":
                item["_prompt_tokens"] = value
            elif name == "vllm:generation_tokens_total":
                item["_generation_tokens"] = value
            elif name == "vllm:e2e_request_latency_seconds_sum":
                item["_time_e2e_sum"] = value
            elif name == "vllm:request_queue_time_seconds_sum":
                item["_time_queue_sum"] = value
            elif name == "vllm:e2e_request_latency_seconds_count":
                item["_request_count"] = value

        for series_id, item in by_model.items():
            request_count = float(item.get("_request_count", 0) or 0)
            time_e2e_sum = float(item.get("_time_e2e_sum", 0) or 0)
            prompt_tokens = float(item.get("_prompt_tokens", 0) or 0)
            generation_tokens = float(item.get("_generation_tokens", 0) or 0)
            time_queue_sum = float(item.get("_time_queue_sum", 0) or 0)
            prompt_tokens_per_second = round(prompt_tokens / time_e2e_sum, 2) if time_e2e_sum > 0 else 0
            tokens_per_second = round(generation_tokens / time_e2e_sum, 2) if time_e2e_sum > 0 else 0
            prompt_time_to_first_token = round(time_queue_sum / request_count, 3) if request_count > 0 and time_queue_sum > 0 else 0
            models[series_id] = {
                "series_id": series_id,
                "engine_key": item["engine_key"],
                "engine_name": item["engine_name"],
                "model_name": item["model_name"],
                "type": "vllm",
                "prompt_tokens_per_second": prompt_tokens_per_second,
                "prompt_time_to_first_token": prompt_time_to_first_token,
                "tokens_per_second": tokens_per_second,
            }

    # Fetch vLLM metrics via Docker exec API. vLLM exposes engine/model labels.
    try:
        metrics_text = docker_exec("vllm-runtime", ["curl", "-s", "http://localhost:8000/metrics"])
        if metrics_text:
            by_model: dict[str, dict[str, object]] = {}

            for line in metrics_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parsed = parse_prometheus_metric(line)
                if not parsed:
                    continue
                name, labels, value = parsed
                model_name = labels.get("model_name")
                engine_id = labels.get("engine", "0")
                if not model_name:
                    continue

                series_id = f"vllm:{engine_id}:{model_name}"
                item = by_model.setdefault(
                    series_id,
                    {
                        "series_id": series_id,
                        "engine_key": f"vllm:{engine_id}",
                        "engine_name": f"vLLM engine {engine_id}",
                        "model_name": model_name,
                        "type": "vllm",
                        "_prompt_tokens": 0.0,
                        "_generation_tokens": 0.0,
                        "_time_e2e_sum": 0.0,
                        "_time_queue_sum": 0.0,
                        "_request_count": 0.0,
                    },
                )

                if name == "vllm:prompt_tokens_total":
                    item["_prompt_tokens"] = value
                elif name == "vllm:generation_tokens_total":
                    item["_generation_tokens"] = value
                elif name == "vllm:e2e_request_latency_seconds_sum":
                    item["_time_e2e_sum"] = value
                elif name == "vllm:request_queue_time_seconds_sum":
                    item["_time_queue_sum"] = value
                elif name == "vllm:e2e_request_latency_seconds_count":
                    item["_request_count"] = value

            for series_id, item in by_model.items():
                request_count = float(item.get("_request_count", 0) or 0)
                time_e2e_sum = float(item.get("_time_e2e_sum", 0) or 0)
                if request_count <= 0 or time_e2e_sum <= 0:
                    continue

                prompt_tokens = float(item.get("_prompt_tokens", 0) or 0)
                generation_tokens = float(item.get("_generation_tokens", 0) or 0)
                time_queue_sum = float(item.get("_time_queue_sum", 0) or 0)
                models[series_id] = {
                    "series_id": series_id,
                    "engine_key": item["engine_key"],
                    "engine_name": item["engine_name"],
                    "model_name": item["model_name"],
                    "type": "vllm",
                    "prompt_tokens_per_second": round(prompt_tokens / time_e2e_sum, 2),
                    "prompt_time_to_first_token": round(time_queue_sum / request_count, 3) if time_queue_sum > 0 else 0,
                    "tokens_per_second": round(generation_tokens / time_e2e_sum, 2),
                }

    except Exception:
        pass

    # Fetch AEON dedicated vLLM metrics via Docker exec API.
    try:
        metrics_text = docker_exec("aeon-vllm", ["curl", "-s", "http://localhost:8000/metrics"])
        if metrics_text:
            by_model: dict[str, dict[str, object]] = {}

            for line in metrics_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parsed = parse_prometheus_metric(line)
                if not parsed:
                    continue
                name, labels, value = parsed
                model_name = labels.get("model_name")
                engine_id = labels.get("engine", "0")
                if not model_name:
                    continue

                series_id = f"aeon-vllm:{engine_id}:{model_name}"
                item = by_model.setdefault(
                    series_id,
                    {
                        "series_id": series_id,
                        "engine_key": f"aeon-vllm:{engine_id}",
                        "engine_name": f"AEON vLLM engine {engine_id}",
                        "model_name": model_name,
                        "type": "vllm",
                        "_prompt_tokens": 0.0,
                        "_generation_tokens": 0.0,
                        "_time_e2e_sum": 0.0,
                        "_time_queue_sum": 0.0,
                        "_request_count": 0.0,
                    },
                )

                if name == "vllm:prompt_tokens_total":
                    item["_prompt_tokens"] = value
                elif name == "vllm:generation_tokens_total":
                    item["_generation_tokens"] = value
                elif name == "vllm:e2e_request_latency_seconds_sum":
                    item["_time_e2e_sum"] = value
                elif name == "vllm:request_queue_time_seconds_sum":
                    item["_time_queue_sum"] = value
                elif name == "vllm:e2e_request_latency_seconds_count":
                    item["_request_count"] = value

            for series_id, item in by_model.items():
                request_count = float(item.get("_request_count", 0) or 0)
                time_e2e_sum = float(item.get("_time_e2e_sum", 0) or 0)
                if request_count <= 0 or time_e2e_sum <= 0:
                    continue

                prompt_tokens = float(item.get("_prompt_tokens", 0) or 0)
                generation_tokens = float(item.get("_generation_tokens", 0) or 0)
                time_queue_sum = float(item.get("_time_queue_sum", 0) or 0)
                models[series_id] = {
                    "series_id": series_id,
                    "engine_key": item["engine_key"],
                    "engine_name": item["engine_name"],
                    "model_name": item["model_name"],
                    "type": "vllm",
                    "prompt_tokens_per_second": round(prompt_tokens / time_e2e_sum, 2),
                    "prompt_time_to_first_token": round(time_queue_sum / request_count, 3) if time_queue_sum > 0 else 0,
                    "tokens_per_second": round(generation_tokens / time_e2e_sum, 2),
                }

    except Exception:
        pass

    for container_name, engine_prefix, series_prefix in (
        ("deepseek-spark-vllm", "DeepSeek Spark vLLM engine", "deepseek-spark-vllm"),
        ("deepseek-spark-mini-vllm", "DeepSeek Spark Mini vLLM engine", "deepseek-spark-mini-vllm"),
    ):
        try:
            collect_vllm_metrics(container_name, engine_prefix, series_prefix)
        except Exception:
            pass

    # Fetch llama.cpp metrics via Docker exec API. llama.cpp exposes one runtime model per process.
    try:
        metrics_text = docker_exec("llamacpp-runtime", ["curl", "-s", "http://localhost:8080/metrics"])
        if metrics_text:
            tpp = 0.0
            toks = 0.0
            model_name = parse_model_from_command("llamacpp-runtime")

            for line in metrics_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parsed = parse_prometheus_metric(line)
                if not parsed:
                    continue
                name, labels, value = parsed

                if name == "llamacpp:prompt_tokens_seconds":
                    tpp = value
                elif name == "llamacpp:predicted_tokens_seconds":
                    toks = value

            if toks > 0:
                series_id = f"llamacpp:0:{model_name}"
                models[series_id] = {
                    "series_id": series_id,
                    "engine_key": "llamacpp:0",
                    "engine_name": "llama.cpp runtime",
                    "model_name": model_name,
                    "type": "llamacpp",
                    "prompt_tokens_per_second": round(tpp, 2),
                    "prompt_time_to_first_token": 0,
                    "tokens_per_second": round(toks, 2),
                }

    except Exception:
        pass

    return {"models": list(models.values())}


def stats_history_sampler() -> None:
    while True:
        try:
            payload = litellm_stats()
            models = payload.get("models", [])
            if isinstance(models, list):
                record_stats_history(models, "7days")
        except Exception as exc:
            print(f"stats sampler failed: {exc}")
        time.sleep(max(STATS_SAMPLE_SECONDS, 10))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)
        request_path = parsed_path.path
        query = parse_qs(parsed_path.query)

        if request_path == "/api/apps":
            try:
                apps = portal_apps(self)
                self.send_json({"title": TITLE, "refreshSeconds": int(REFRESH_SECONDS), "apps": apps})
            except Exception as exc:
                self.send_json({"title": TITLE, "refreshSeconds": int(REFRESH_SECONDS), "apps": [], "error": str(exc)})
            return
        if request_path == "/api/system":
            try:
                self.send_json(system_snapshot())
            except Exception as exc:
                self.send_json({"error": str(exc)})
            return
        if request_path == "/api/litellm-stats":
            try:
                range_name = (query.get("range") or ["hour"])[0]
                self.send_json(stats_with_history(range_name))
            except Exception as exc:
                self.send_json({"models": [], "error": str(exc)})
            return
        if request_path == "/healthz":
            self.send_json({"ok": True})
            return
        if request_path in ("/", "/index.html"):
            self.send_file(ROOT / "index.html")
            return
        safe_path = request_path.lstrip("/")
        target = (ROOT / safe_path).resolve()
        if ROOT in target.parents and target.is_file():
            self.send_file(target)
            return
        self.send_error(404)

    def send_json(self, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline';")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline';")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    threading.Thread(target=stats_history_sampler, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Serving {TITLE} on 0.0.0.0:{PORT}")
    server.serve_forever()
