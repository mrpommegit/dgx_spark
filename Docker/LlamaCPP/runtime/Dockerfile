ARG CUDA_VERSION=12.1.0
ARG UBUNTU_VERSION=22.04

FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS build

RUN apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y gcc g++ build-essential cmake python3 python3-pip git libssl-dev libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp.git

WORKDIR /app/llama.cpp

# Build llama.cpp with CUDA support
RUN cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_EXE_LINKER_FLAGS="-Wl,--allow-shlib-undefined" . && \
    cmake --build build --config Release -j$(nproc)

# Runtime stage
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}

RUN apt-get update -y && \
    apt-get install -y libgomp1 curl && \
    apt autoremove -y && \
    apt clean -y && \
    rm -rf /tmp/* /var/tmp/* && \
    find /var/cache/apt/archives /var/lib/apt/lists -not -name lock -type f -delete

# Copy binaries and libraries
COPY --from=build /app/llama.cpp/build/bin/llama-server /app/llama-server
COPY --from=build /app/llama.cpp/build/bin/libllama-server-impl.so* /app/
COPY --from=build /app/llama.cpp/build/bin/libllama.so* /app/
COPY --from=build /app/llama.cpp/build/bin/libggml*.so* /app/
COPY --from=build /app/llama.cpp/build/bin/libggml-cpu.so* /app/
COPY --from=build /app/llama.cpp/build/bin/libggml-cuda.so* /app/
COPY --from=build /app/llama.cpp/build/bin/libllama-common.so* /app/
COPY --from=build /app/llama.cpp/build/bin/libmtmd.so* /app/
COPY --from=build /app/llama.cpp/build/bin/libggml-backend.so* /app/

ENV LD_LIBRARY_PATH=/app:$LD_LIBRARY_PATH

WORKDIR /app

EXPOSE 8080

HEALTHCHECK CMD [ "curl", "-f", "http://localhost:8080/health" ]

ENTRYPOINT [ "/app/llama-server" ]
