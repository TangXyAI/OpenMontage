"""Local video post-enhancement through ComfyUI.

Two bundled API workflows:

- ``face_refine`` — H3 FaceRefine (face track, crop, per-frame denoise,
  stitch back, original audio).
- ``video_upscale`` — SeedVR2 3B FP8 detail upscale.

This module implements the tool contract, input validation, model merging
and pure workflow patch construction. Submission, uploads and media
validation land with the execution task.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ToolStability,
    ToolTier,
    ToolRuntime,
)
from tools._comfyui.client import ComfyUIClient

_WORKFLOWS = Path(__file__).resolve().parent.parent / "_comfyui" / "workflows"

# Bundled API-format workflows, one per supported operation.  Node ``23``
# is the output node in both (VHS_VideoCombine / SaveVideo).
_WORKFLOW_FILES = {
    "face_refine": "enhance_face_refine_h3_api.json",
    "video_upscale": "enhance_seedvr2_3b_api.json",
}
_OUTPUT_NODE = "23"

_OPERATIONS = tuple(_WORKFLOW_FILES)

# Default model filenames, matching the locally installed stack.  A caller
# may override any key through the ``models`` input.
DEFAULTS: dict[str, dict[str, str]] = {
    "face_refine": {
        "unet": "Minimax-h3_Singularity_ref2va_v2_int8.safetensors",
        "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "vae_video": "minimax_h3_video_vae_fp16.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "lora": "MiniMax-H3\\加速\\PikaFlex-Turbo-8步高清多模态参考视频加速.safetensors",
        "detector": "face_yolov8n.pt",
    },
    "video_upscale": {
        "seedvr2_dit": "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
        "seedvr2_vae": "ema_vae_fp16.safetensors",
    },
}


class ComfyUIEnhance(BaseTool):
    name = "comfyui_enhance"
    version = "0.1.0"
    tier = ToolTier.ENHANCE
    capability = "enhancement"
    provider = "comfyui"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU

    dependencies = []
    install_instructions = (
        "Start a ComfyUI server and install the H3 FaceRefine and SeedVR2 "
        "custom nodes plus their models.\n"
        "Set COMFYUI_ENHANCE_SERVER_URL to give enhancement its own server, "
        "or the shared COMFYUI_SERVER_URL (default http://localhost:8188)."
    )
    agent_skills = ["video-enhancement"]
    fallback = None

    capabilities = ["face_refinement", "video_upscaling", "detail_enhancement"]

    input_schema = {
        "type": "object",
        "required": ["operation", "input_path", "output_path"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": list(_OPERATIONS),
                "description": (
                    "face_refine uses the H3 FaceRefine workflow (single "
                    "close-up face); video_upscale uses SeedVR2 3B."
                ),
            },
            "input_path": {
                "type": "string",
                "description": "Source video path.",
            },
            "output_path": {
                "type": "string",
                "description": "Destination video; must stay inside project_dir.",
            },
            "project_dir": {
                "type": "string",
                "description": "Project workspace that output_path must stay inside.",
            },
            "reference_image_paths": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": (
                    "face_refine only: exactly two images, the identity "
                    "close-up (node 6) and the wardrobe/full-body reference "
                    "(node 7)."
                ),
            },
            "prompt": {
                "type": "string",
                "description": "face_refine only: subject and identity description.",
            },
            "denoise": {
                "type": "number",
                "default": 0.4,
                "description": "face_refine main denoise strength.",
            },
            "face_select": {
                "type": "string",
                "default": "largest_face",
                "description": "face_refine H3FaceTrackCrop select mode.",
            },
            "identity_threshold": {
                "type": "number",
                "default": 0.28,
                "description": "face_refine identity tracking threshold.",
            },
            "face_denoise_multiplier": {
                "type": "number",
                "default": 1.0,
                "description": (
                    "face_refine H3PerFrameDenoise multiplier for both small "
                    "and large faces."
                ),
            },
            "resolution": {
                "type": "integer",
                "default": 1080,
                "description": "video_upscale target short-edge resolution.",
            },
            "max_resolution": {
                "type": "integer",
                "default": 0,
                "description": "video_upscale extra cap; 0 means no extra cap.",
            },
            "batch_size": {
                "type": "integer",
                "default": 5,
                "description": "video_upscale batch size.",
            },
            "temporal_overlap": {
                "type": "integer",
                "default": 3,
                "description": "video_upscale temporal overlap between batches.",
            },
            "color_correction": {
                "type": "string",
                "enum": ["lab", "wavelet", "none"],
                "default": "lab",
                "description": "video_upscale color correction mode.",
            },
            "seed": {
                "type": "integer",
                "default": 42,
                "description": "Sampling seed for both operations.",
            },
            "models": {
                "type": "object",
                "default": {},
                "description": (
                    "Override default model filenames. face_refine keys: unet, "
                    "clip, vae_video, vae_audio, lora, detector. video_upscale "
                    "keys: seedvr2_dit, seedvr2_vae."
                ),
            },
            "server_url": {
                "type": "string",
                "description": (
                    "Override COMFYUI_ENHANCE_SERVER_URL / COMFYUI_SERVER_URL "
                    "for this call."
                ),
            },
            "timeout_seconds": {
                "type": "integer",
                "default": 7200,
                "description": "Budget for the long-running enhancement job.",
            },
        },
    }

    def __init__(self, client: Any = None) -> None:
        self._client = client or ComfyUIClient(capability="enhance")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(inputs: dict[str, Any]) -> str | None:
        """Validate an enhancement request without touching the network.

        Returns an error string or ``None``.
        """
        operation = inputs.get("operation")
        if operation not in _OPERATIONS:
            return (
                f"Unknown operation {operation!r}; expected one of "
                f"{', '.join(_OPERATIONS)}."
            )
        for field in ("input_path", "output_path"):
            if not str(inputs.get(field) or "").strip():
                return f"comfyui_enhance requires {field} for operation {operation!r}."

        if operation == "face_refine":
            refs = inputs.get("reference_image_paths") or []
            if len(refs) != 2:
                return (
                    "face_refine requires exactly two reference images "
                    "(identity close-up and wardrobe/full-body reference); "
                    f"got {len(refs)}."
                )
            if not str(inputs.get("prompt") or "").strip():
                return "face_refine requires a non-empty prompt."

        project_dir = inputs.get("project_dir")
        if project_dir:
            try:
                output = Path(inputs["output_path"]).resolve()
                root = Path(project_dir).resolve()
            except (OSError, ValueError) as exc:
                return f"Could not resolve output_path against project_dir: {exc}"
            if not output.is_relative_to(root):
                return "output_path must stay inside project_dir (the project workspace)."
        return None

    # ------------------------------------------------------------------
    # Model and workflow binding
    # ------------------------------------------------------------------

    @staticmethod
    def _merged_models(inputs: dict[str, Any]) -> dict[str, str]:
        """Default model filenames for the operation, overridden by ``models``."""
        operation = str(inputs.get("operation", "face_refine"))
        return {
            **DEFAULTS.get(operation, {}),
            **(inputs.get("models") or {}),
        }

    @staticmethod
    def _workflow_patches(
        operation: str,
        inputs: dict[str, Any],
        *,
        source_fps: float,
        source_name: str,
        ref_names: list[str],
        output_prefix: str,
    ) -> dict[str, dict[str, Any]]:
        """Pure node bindings for a bundled enhancement workflow.

        ``source_name`` is the node-1 path for face_refine (VHS_LoadVideoPath
        accepts an absolute path) and the uploaded server filename for
        video_upscale (LoadVideo only resolves names in ComfyUI's input dir).
        """
        models = ComfyUIEnhance._merged_models({**inputs, "operation": operation})

        if operation == "face_refine":
            if len(ref_names) != 2:
                raise ValueError(
                    "face_refine needs exactly two uploaded reference names"
                )
            multiplier = inputs.get("face_denoise_multiplier", 1.0)
            return {
                "1": {"video": source_name},
                "2": {
                    "select": inputs.get("face_select", "largest_face"),
                    "identity_threshold": inputs.get("identity_threshold", 0.28),
                    "detector": models["detector"],
                },
                "4": {"vae_name": models["vae_video"]},
                "5": {"vae_name": models["vae_audio"]},
                "6": {"image": ref_names[0]},
                "7": {"image": ref_names[1]},
                "9": {"prompt": inputs.get("prompt", "")},
                "12": {"lora_name": models["lora"]},
                "16": {"denoise": inputs.get("denoise", 0.4)},
                "17": {"noise_seed": inputs.get("seed", 42)},
                "23": {
                    "frame_rate": float(source_fps),
                    "filename_prefix": output_prefix,
                },
                "31": {
                    "denoise_multiplier_small_face": multiplier,
                    "denoise_multiplier_large_face": multiplier,
                },
                "108": {"unet_name": models["unet"]},
                "109": {"clip_name": models["clip"]},
            }

        if operation == "video_upscale":
            return {
                "10": {
                    "resolution": inputs.get("resolution", 1080),
                    "max_resolution": inputs.get("max_resolution", 0),
                    "batch_size": inputs.get("batch_size", 5),
                    "temporal_overlap": inputs.get("temporal_overlap", 3),
                    "seed": inputs.get("seed", 42),
                    "color_correction": inputs.get("color_correction", "lab"),
                },
                "13": {"model": models["seedvr2_vae"]},
                "14": {"model": models["seedvr2_dit"]},
                "21": {"file": source_name},
                "23": {"filename_prefix": output_prefix},
            }

        raise ValueError(f"Unsupported enhancement operation: {operation!r}")
