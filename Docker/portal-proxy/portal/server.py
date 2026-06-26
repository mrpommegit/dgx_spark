import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
HOST_ROOT = Path(os.getenv("PORTAL_HOST_ROOT", "/host"))
SOCKET_PATH = "/var/run/docker.sock"
PORT = int(os.getenv("PORTAL_INTERNAL_PORT", "8080"))
TITLE = os.getenv("PORTAL_TITLE", "DGX Spark Portal")
REFRESH_SECONDS = os.getenv("PORTAL_REFRESH_SECONDS", "5")

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


def litellm_stats() -> dict[str, dict[str, object]]:
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

            return body.decode("utf-8", errors="replace")
        except Exception:
            return ""

    # Fetch vLLM metrics via Docker exec API
    try:
        metrics_text = docker_exec("vllm-runtime", ["curl", "-s", "http://localhost:8000/metrics"])
        if metrics_text:
            prompt_tokens = 0
            generation_tokens = 0
            time_e2e_sum = 0
            time_queue_sum = 0
            request_count = 0

            for line in metrics_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("vllm:prompt_tokens_total{") and "} " in line:
                    prompt_tokens = float(line.split("} ")[1])
                elif line.startswith("vllm:generation_tokens_total{") and "} " in line:
                    generation_tokens = float(line.split("} ")[1])
                elif line.startswith("vllm:e2e_request_latency_seconds_sum{") and "} " in line:
                    time_e2e_sum = float(line.split("} ")[1])
                elif line.startswith("vllm:request_queue_time_seconds_sum{") and "} " in line:
                    time_queue_sum = float(line.split("} ")[1])
                elif line.startswith("vllm:e2e_request_latency_seconds_count{") and "} " in line:
                    request_count = float(line.split("} ")[1])

            if request_count > 0 and time_e2e_sum > 0:
                tpp = (prompt_tokens / time_e2e_sum) if time_e2e_sum > 0 else 0
                tft = (time_queue_sum / request_count) if time_queue_sum > 0 else 0
                toks = (generation_tokens / time_e2e_sum) if time_e2e_sum > 0 else 0

                models["local-vllm"] = {
                    "model_name": "local-vllm",
                    "type": "vllm",
                    "prompt_tokens_per_second": round(tpp, 2),
                    "prompt_time_to_first_token": round(tft, 3),
                    "tokens_per_second": round(toks, 2),
                }

    except Exception:
        pass

    # Fetch llama.cpp metrics via Docker exec API
    try:
        metrics_text = docker_exec("llamacpp-runtime", ["curl", "-s", "http://localhost:8080/metrics"])
        if metrics_text:
            tpp = 0.0
            toks = 0.0

            for line in metrics_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # llama.cpp provides direct gauge metrics for throughput
                if line.startswith("llamacpp:prompt_tokens_seconds ") and not "}" in line:
                    tpp = float(line.split()[1])
                elif line.startswith("llamacpp:predicted_tokens_seconds ") and not "}" in line:
                    toks = float(line.split()[1])

            if toks > 0:
                models["local-llamacpp"] = {
                    "model_name": "local-llamacpp",
                    "type": "llamacpp",
                    "prompt_tokens_per_second": round(tpp, 2),
                    "prompt_time_to_first_token": 0,
                    "tokens_per_second": round(toks, 2),
                }

    except Exception:
        pass

    return {"models": list(models.values())}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        if self.path == "/api/apps":
            try:
                apps = portal_apps(self)
                self.send_json({"title": TITLE, "refreshSeconds": int(REFRESH_SECONDS), "apps": apps})
            except Exception as exc:
                self.send_json({"title": TITLE, "refreshSeconds": int(REFRESH_SECONDS), "apps": [], "error": str(exc)})
            return
        if self.path == "/api/system":
            try:
                self.send_json(system_snapshot())
            except Exception as exc:
                self.send_json({"error": str(exc)})
            return
        if self.path == "/api/litellm-stats":
            try:
                self.send_json(litellm_stats())
            except Exception as exc:
                self.send_json({"models": [], "error": str(exc)})
            return
        if self.path == "/healthz":
            self.send_json({"ok": True})
            return
        if self.path in ("/", "/index.html"):
            self.send_file(ROOT / "index.html")
            return
        safe_path = self.path.split("?", 1)[0].lstrip("/")
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
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Serving {TITLE} on 0.0.0.0:{PORT}")
    server.serve_forever()
