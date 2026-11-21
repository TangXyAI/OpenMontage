"""Filesystem-only readiness check for the local post-enhancement routes.

Two enhancement routes run on the same local ComfyUI install:

* ``face_refine`` — the ``ComfyUI-H3-FaceRefine`` pack (which also needs
  ``comfyui-videohelpersuite`` for video loading/combining) plus the H3
  checkpoint set, the acceleration LoRA, and a face detector.
* ``video_upscale`` — the ``seedvr2_videoupscaler`` pack plus the SeedVR2 3B
  DiT and its VAE.

The agent asks this helper whether an enhancement route can run before it
offers that route to the user. The check is deliberately offline: it reads
ComfyUI's version file, the ``custom_nodes`` directory, and the configured
model roots. The caller probes the ComfyUI server and passes
``server_running``; this function makes no network calls.

Each route's ``ready`` flag reflects only on-disk state (nodes and model
files), so a stopped server does not hide a route that is otherwise complete.
The ComfyUI version is shared by both routes: a missing or too-old install
blocks both. SeedVR2 auto-downloads its 3B DiT on first run (about 3.16 GB),
so a missing DiT is only a warning; the VAE cannot be auto-downloaded and is a
blocker. A missing ``insightface`` model only degrades identity tracking, so it
is a warning too.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from lib.comfyui_readiness import (
    MIN_COMFYUI_VERSION,
    MIN_COMFYUI_VERSION_TEXT,
    find_exact_file,
    missing_message,
    model_check,
    normalise_roots,
    read_comfyui_version,
    roots_text,
    version_tuple,
    walk_files,
)

DEFAULT_MODELS = {
    "unet": "Minimax-h3_Singularity_ref2va_v2_int8.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae_video": "minimax_h3_video_vae_fp16.safetensors",
    "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
    "lora": (
        r"MiniMax-H3\加速\PikaFlex-Turbo-8步高清多模态参考视频加速.safetensors"
    ),
    "detector": "face_yolov8n.pt",
    "seedvr2_dit": "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
    "seedvr2_vae": "ema_vae_fp16.safetensors",
}

REQUIRED_NODES = {
    "face_refine": ("ComfyUI-H3-FaceRefine", "comfyui-videohelpersuite"),
    "video_upscale": ("seedvr2_videoupscaler",),
}

ROUTE_MODELS = {
    "face_refine": ("unet", "clip", "vae_video", "vae_audio", "lora", "detector"),
    "video_upscale": ("seedvr2_dit", "seedvr2_vae"),
}

MODEL_LABELS = {
    "unet": "FaceRefine UNET",
    "clip": "FaceRefine CLIP",
    "vae_video": "FaceRefine video VAE",
    "vae_audio": "FaceRefine audio VAE",
    "lora": "FaceRefine acceleration LoRA",
    "detector": "face detector",
    "seedvr2_dit": "SeedVR2 3B DiT",
    "seedvr2_vae": "SeedVR2 VAE",
}


def _expected_basename(expected: str) -> str:
    """Return the file name of a configured model path.

    Model names may carry a relative subdirectory (the LoRA lives under
    ``MiniMax-H3/加速/``), but readiness matches files by basename anywhere
    under the model roots, like the other model checks.
    """
    return Path(expected.replace("\\", "/")).name


def _installed_node_packs(custom_nodes: Path) -> dict[str, Path]:
    """Map casefolded directory names under ``custom_nodes`` to their paths."""
    try:
        entries = list(custom_nodes.iterdir())
    except OSError:
        return {}
    return {entry.name.casefold(): entry for entry in entries if entry.is_dir()}


def _has_insightface(files_by_root: dict[Path, list[Path]]) -> bool:
    """True when a walked model file lives under an ``insightface`` directory."""
    for files in files_by_root.values():
        for path in files:
            if any(part.casefold() == "insightface" for part in path.parts):
                return True
    return False


def check_enhancement_readiness(
    comfyui_root: str | Path,
    model_roots: Sequence[str | Path],
    *,
    server_running: bool,
    models: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Check whether the local post-enhancement routes can run.

    Args:
        comfyui_root: ComfyUI installation root containing
            ``comfyui_version.py`` and ``custom_nodes/``.
        model_roots: Directories searched recursively for model files.
        server_running: Whether the ComfyUI server is currently reachable.
            The caller probes the server; this function makes no network calls.
        models: Optional overrides for the expected model file names, keyed by
            the names in :data:`DEFAULT_MODELS`.

    Returns:
        ``{"ready", "server_running", "comfyui_version", "checks", "blockers",
        "warnings", "routes", "ready_routes"}``. ``routes`` maps
        ``"face_refine"`` and ``"video_upscale"`` to
        ``{"ready", "blockers", "warnings", "models"}``. A route's ``ready``
        reflects only its nodes and model files, not the server; the top-level
        ``ready`` is true only when the server is running and at least one
        route is ready. The top-level ``blockers`` carry shared problems (the
        server is down, or ComfyUI is missing/too old).
    """
    comfy_root = Path(comfyui_root)
    roots = normalise_roots(model_roots)
    expected_models = {**DEFAULT_MODELS, **(models or {})}

    checks: dict[str, dict[str, object]] = {}
    shared_blockers: list[str] = []

    version_file = comfy_root / "comfyui_version.py"
    version = read_comfyui_version(version_file)
    if version is None:
        version_detail = (
            f"No __version__ found in {version_file} "
            f"(required ComfyUI >= {MIN_COMFYUI_VERSION_TEXT})"
        )
        shared_blockers.append(
            f"Missing ComfyUI version in {version_file}; "
            f"required >= {MIN_COMFYUI_VERSION_TEXT}"
        )
    elif version_tuple(version) < MIN_COMFYUI_VERSION:
        version_detail = (
            f"ComfyUI {version} is older than the required "
            f"{MIN_COMFYUI_VERSION_TEXT}"
        )
        shared_blockers.append(
            f"ComfyUI {version} is older than required "
            f"{MIN_COMFYUI_VERSION_TEXT} (searched {version_file})"
        )
    else:
        version_detail = (
            f"ComfyUI {version} satisfies >= {MIN_COMFYUI_VERSION_TEXT}"
        )
    checks["comfyui_version"] = {
        "ok": not shared_blockers,
        "path": str(version_file) if version_file.is_file() else None,
        "detail": version_detail,
    }

    custom_nodes = comfy_root / "custom_nodes"
    installed_nodes = _installed_node_packs(custom_nodes)

    checks["server_running"] = {
        "ok": bool(server_running),
        "path": None,
        "detail": (
            "ComfyUI server is running"
            if server_running
            else "ComfyUI server is not running"
        ),
    }

    files_by_root = {root: walk_files(root) for root in roots}

    routes: dict[str, dict[str, object]] = {}
    for route_name, node_packs in REQUIRED_NODES.items():
        route_blockers: list[str] = list(shared_blockers)
        route_warnings: list[str] = []
        route_models: dict[str, str | None] = {}

        for node_pack in node_packs:
            node_path = installed_nodes.get(node_pack.casefold())
            node_ok = node_path is not None
            checks[f"custom_node:{node_pack}"] = {
                "ok": node_ok,
                "path": str(node_path) if node_ok else None,
                "detail": (
                    f"Custom node pack installed: {node_path}"
                    if node_ok
                    else f"Missing custom node pack '{node_pack}' "
                    f"(searched {custom_nodes})"
                ),
            }
            if not node_ok:
                route_blockers.append(
                    f"Missing custom node pack '{node_pack}' under {custom_nodes}"
                )

        for model_key in ROUTE_MODELS[route_name]:
            expected = expected_models[model_key]
            found = find_exact_file(
                _expected_basename(expected), roots, files_by_root
            )
            label = MODEL_LABELS[model_key]
            checks[f"{route_name}.{model_key}"] = model_check(
                found, label, expected, roots
            )
            route_models[model_key] = str(found) if found is not None else None

            if found is None:
                if route_name == "video_upscale" and model_key == "seedvr2_dit":
                    route_warnings.append(
                        f"{label} '{expected}' not found in model roots: "
                        f"{roots_text(roots)}; first run downloads ~3.16 GB"
                    )
                else:
                    route_blockers.append(
                        missing_message(label, expected, roots)
                    )

        if route_name == "face_refine" and not _has_insightface(files_by_root):
            route_warnings.append(
                "insightface model directory not found in model roots: "
                f"{roots_text(roots)}; identity_model='insightface' will "
                "degrade identity tracking but does not block this route"
            )

        routes[route_name] = {
            "ready": not route_blockers,
            "blockers": route_blockers,
            "warnings": route_warnings,
            "models": route_models,
        }

    ready_routes = [name for name, route in routes.items() if route["ready"]]

    blockers = list(shared_blockers)
    if not server_running:
        blockers.append(
            "ComfyUI server is not running; start ComfyUI before local "
            "post-enhancement"
        )

    warnings: list[str] = []
    for route in routes.values():
        for warning in route["warnings"]:
            if warning not in warnings:
                warnings.append(warning)

    return {
        "ready": bool(server_running) and bool(ready_routes),
        "server_running": bool(server_running),
        "comfyui_version": version,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "routes": routes,
        "ready_routes": ready_routes,
    }
