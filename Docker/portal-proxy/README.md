# DGX Spark Portal Proxy

This stack publishes a dynamic portal on port 80. The portal reads the Docker API
through the local Docker socket and displays running containers that opt in with
`portal.*` labels. It also shows host health gauges for VRAM, RAM, CPU, disk
space, a network table, and Tailscale on/off status.

Open the portal at:

```text
http://<box-ip>/
```

## Start

```bash
cd Docker/portal-proxy
cp .env.example .env 2>/dev/null || true
docker compose up -d
```

The service binds `${PORTAL_PORT:-80}` on the host and serves the UI from port
`8080` inside the container.

## Publishing an App

Add labels to any Docker Compose service that exposes a web UI:

```yaml
labels:
  portal.enable: "true"
  portal.name: "ComfyUI"
  portal.description: "Image and video generation"
  portal.port: "8188"
  portal.icon: "image"
  portal.order: "10"
```

Use `portal.protocol: "https"` for services that require HTTPS (like Portainer):

When the container is running, the tile appears automatically. When it stops, the
tile disappears at the next refresh. Each tile also shows live Docker stats for
that container: CPU percent, RAM percent, and aggregate block I/O.

Use `portal.protocol: "https"` for services that require HTTPS (like Portainer).
Use `portal.url` only when the app should open a fixed URL. Without it, the
portal builds `http://<box-ip>:<portal.port>` (or `https://` if protocol is set)
from the current request host.

## Security

The portal mounts `/var/run/docker.sock` read-only so it can list containers and
read per-container stats. It also mounts the host root read-only to read
`/proc` and disk usage for the global gauges. Only containers with
`portal.enable=true` are shown, and the browser never sees the Docker socket
directly. Keep this portal on a trusted LAN or behind a VPN.
