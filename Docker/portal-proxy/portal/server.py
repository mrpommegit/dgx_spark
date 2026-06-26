import json
import os
import shutil
import socket
import subprocess
import time
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
