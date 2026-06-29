#!/usr/bin/env python3
"""Runtime patches from 0xSero/deepseek-spark for REAP DeepSeek-V4 on GB10."""

from __future__ import annotations

from pathlib import Path

ROUTER_TARGET = Path(
    "/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/"
    "fused_moe/router/fused_topk_bias_router.py"
)
MXFP4_TARGET = Path(
    "/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/"
    "quantization/mxfp4.py"
)
IMPORT_UTILS_TARGET = Path(
    "/usr/local/lib/python3.12/dist-packages/vllm/utils/import_utils.py"
)
FLASHINFER_CUDA_IPC_TARGET = Path(
    "/usr/local/lib/python3.12/dist-packages/flashinfer/comm/cuda_ipc.py"
)

HASCUTEDSL_OLD = (
    '    """Whether the optional `cutlass` package is available and importable."""\n'
    "    try:\n"
    "        import cutlass  # noqa: F401\n"
    "    except Exception:\n"
    "        return False\n"
    "    return True"
)
HASCUTEDSL_NEW = (
    '    """Whether the optional `cutlass` package is available and importable."""\n'
    "    import os as _os\n"
    '    if _os.environ.get("K160_DISABLE_CUTEDSL", "0") == "1":\n'
    "        return False\n"
    "    try:\n"
    "        import cutlass  # noqa: F401\n"
    "    except Exception:\n"
    "        return False\n"
    "    return True"
)

SUPPORTED = "(16, 32, 64, 128, 192, 256, 320, 384, 512)"

ROUTER_OLD = "    if not rocm_aiter_ops.is_fused_moe_enabled():"
ROUTER_NEW = (
    "    # REAP DeepSeek-V4 checkpoints prune to nonstandard routed-expert\n"
    "    # counts. The fused sqrtsoftplus CUDA top-k kernel is only instantiated\n"
    "    # for a fixed set of counts. Route others to the Torch fallback.\n"
    "    if not rocm_aiter_ops.is_fused_moe_enabled() and not (\n"
    '        scoring_func == "sqrtsoftplus"\n'
    f"        and gating_output.shape[-1] not in {SUPPORTED}\n"
    "    ):"
)

MXFP4_OLD = (
    "    def process_weights_after_loading(self, layer):\n"
    "        w13 = layer.w13_weight\n"
    "        w2 = layer.w2_weight\n"
    "        w13_scale = layer.w13_weight_scale\n"
    "        w2_scale = layer.w2_weight_scale\n"
    '        w13_bias = getattr(layer, "w13_bias", None)\n'
    '        w2_bias = getattr(layer, "w2_bias", None)\n'
    "\n"
    "        if self.mxfp4_backend == Mxfp4MoeBackend.NONE:\n"
    "            return\n"
    "\n"
    "        self._setup_kernel(layer, w13, w2, w13_scale, w2_scale, w13_bias, w2_bias)"
)
MXFP4_NEW = (
    MXFP4_OLD
    + "\n"
    "        import torch as _t, gc as _gc\n"
    "        _gc.collect()\n"
    "        _t.cuda.empty_cache()\n"
    "        try:\n"
    '            print("[k160-moe-patch] layer setup alloc=%.1fGB reserved=%.1fGB"\n'
    "                  % (_t.cuda.memory_allocated() / 1e9, _t.cuda.memory_reserved() / 1e9),\n"
    "                  flush=True)\n"
    "        except Exception:\n"
    "            pass"
)

CUDA_IPC_OLD = (
    "        if so_file is None:\n"
    '            so_file = find_loaded_library("libcudart")\n'
    '            assert so_file is not None, "libcudart is not loaded in the current process"'
)
CUDA_IPC_NEW = (
    "        if so_file is None:\n"
    '            loaded_cudart = find_loaded_library("libcudart")\n'
    "            preferred_cudart = (\n"
    '                "/usr/local/lib/python3.12/dist-packages/nvidia/cu13/lib/"\n'
    '                "libcudart.so.13"\n'
    "            )\n"
    "            import os as _os\n"
    "            if loaded_cudart and \"libcudart_stub\" not in loaded_cudart:\n"
    "                so_file = loaded_cudart\n"
    "            elif _os.path.exists(preferred_cudart):\n"
    "                so_file = preferred_cudart\n"
    "            else:\n"
    "                so_file = loaded_cudart\n"
    '            assert so_file is not None, "libcudart is not loaded in the current process"'
)


def patch_once(target: Path, old: str, new: str) -> str:
    text = target.read_text()
    if new in text:
        return f"PATCH_ALREADY_APPLIED {target.name}"
    if old not in text:
        raise SystemExit(f"PATCH_TARGET_NOT_FOUND {target}")
    if text.count(old) != 1:
        raise SystemExit(f"PATCH_TARGET_NOT_UNIQUE {target} count={text.count(old)}")
    target.write_text(text.replace(old, new, 1))
    return f"PATCH_APPLIED {target.name}"


def maybe_swap_cutedsl() -> None:
    import os
    import subprocess
    import sys

    version = os.environ.get("CUTEDSL_VERSION", "").strip()
    if not version:
        return
    print(f"CUTEDSL_SWAP installing nvidia-cutlass-dsl=={version}", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--force-reinstall",
         "--no-deps", "--no-cache-dir", f"nvidia-cutlass-dsl=={version}"]
    )


def main() -> int:
    import py_compile

    maybe_swap_cutedsl()
    print(patch_once(ROUTER_TARGET, ROUTER_OLD, ROUTER_NEW))
    py_compile.compile(str(ROUTER_TARGET), doraise=True)
    mxfp4_text = MXFP4_TARGET.read_text()
    if (
        "self._setup_kernel(layer, w13, w2, w13_scale, w2_scale, w13_bias, w2_bias)" in mxfp4_text
        and "torch.cuda.empty_cache()" in mxfp4_text
    ):
        print(f"PATCH_ALREADY_EQUIVALENT {MXFP4_TARGET.name}")
    else:
        print(patch_once(MXFP4_TARGET, MXFP4_OLD, MXFP4_NEW))
    py_compile.compile(str(MXFP4_TARGET), doraise=True)
    import_utils_text = IMPORT_UTILS_TARGET.read_text()
    if HASCUTEDSL_NEW in import_utils_text:
        print(f"PATCH_ALREADY_APPLIED {IMPORT_UTILS_TARGET.name}")
    elif HASCUTEDSL_OLD in import_utils_text:
        print(patch_once(IMPORT_UTILS_TARGET, HASCUTEDSL_OLD, HASCUTEDSL_NEW))
    else:
        print(f"PATCH_SKIPPED_NO_CUTEDSL_HELPER {IMPORT_UTILS_TARGET.name}")
    py_compile.compile(str(IMPORT_UTILS_TARGET), doraise=True)
    print(patch_once(FLASHINFER_CUDA_IPC_TARGET, CUDA_IPC_OLD, CUDA_IPC_NEW))
    py_compile.compile(str(FLASHINFER_CUDA_IPC_TARGET), doraise=True)
    print("PATCH_COMPILE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
