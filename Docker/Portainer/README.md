# Portainer Stack

Docker container management UI for DGX Spark.

## Start

```bash
cd Docker/Portainer
cp .env.example .env
docker compose up -d
```

Open the Portainer UI at:

```text
https://<box-ip>:9443
```

On first visit, create an admin user (12+ character password recommended).

## Data Persistence

Portainer data is stored in `~/portainer-data` by default. Change `PORTAINER_DATA_DIR`
in `.env` to use a different location.

The directory is created automatically on first start.

## Portal Integration

Portainer appears in the DGX Spark Portal at `http://<box-ip>/` with a settings icon
and opens on port 9443 (HTTPS).

## Troubleshooting

- If port 9443 is in use, change `PORTAINER_PORT` in `.env`
- To reset Portainer completely: stop the container, remove `~/portainer-data`, then restart
- Portainer requires `/var/run/docker.sock` to manage containers (read-only mount)
