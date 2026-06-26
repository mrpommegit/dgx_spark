FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
CMD ["python", "server.py"]
