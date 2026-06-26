FROM python:3.12-slim-bookworm

ARG COMFYUI_REPO=https://github.com/comfyanonymous/ComfyUI.git
ARG COMFYUI_REF=master
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu130

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        git-lfs \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN git clone --depth 1 --branch "${COMFYUI_REF}" "${COMFYUI_REPO}" ComfyUI \
    && git -C ComfyUI lfs install --local

WORKDIR /opt/ComfyUI

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --index-url "${PYTORCH_INDEX_URL}" torch torchvision torchaudio \
    && python -m pip install -r requirements.txt

COPY docker-entrypoint.sh /usr/local/bin/comfyui-entrypoint
RUN chmod +x /usr/local/bin/comfyui-entrypoint

EXPOSE 8188

ENTRYPOINT ["comfyui-entrypoint"]
CMD ["bash", "-lc", "python main.py ${COMFYUI_ARGS:-} ${COMFYUI_EXTRA_ARGS:-}"]
