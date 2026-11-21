"""Local video post-enhancement through ComfyUI.

Two bundled API workflows:

- ``face_refine`` — H3 FaceRefine (face track, crop, per-frame denoise,
  stitch back, original audio).
- ``video_upscale`` — SeedVR2 3B FP8 detail upscale.

This module implements the tool contract, input validation, model merging,
pure workflow patch construction, ComfyUI submission/download, and the
media-integrity validation (audio streams, frame rate, duration, SSIM) that
guards the downloaded artifact before it replaces a pipeline take.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ToolResult,
    ToolStability,
    ToolTier,
    ToolRuntime,
)
from tools._comfyui.client import ComfyUIClient
from tools._comfyui.metadata import workflow_hash

_WORKFLOWS = Path(__file__).resolve().parent.parent / "_comfyui" / "workflows"

# Bundled API-format workflows, one per supported operation.  Node ``23``
# is the output node in both (VHS_VideoCombine / SaveVideo).
_WORKFLOW_FILES = {
    "face_refine": "enhance_face_refine_h3_api.json",
    "video_upscale": "enhance_seedvr2_3b_api.json",
}
_OUTPUT_NODE = "23"

_OPERATIONS = tuple(_WORKFLOW_FILES)

# SSIM above this means the artifact is virtually identical to the source:
# no face was detected, or the enhancement had no effect.  Not a failure —
# the gate must show it and let the user decide.
_SSIM_UNCHANGED_THRESHOLD = 0.999
# Frame rate must survive the round trip exactly (to probe precision).
_FPS_TOLERANCE = 0.01


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _parse_frame_rate(value: Any) -> float | None:
    """Parse an ffprobe rate such as ``24/1`` or ``24000/1001``."""
    try:
        numerator, _, denominator = str(value).partition("/")
        rate = float(numerator) / float(denominator or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return round(rate, 3) if rate > 0 else None


def _discard(path: Path) -> None:
    """Best-effort removal of an incomplete artifact."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _media_summary(probe: dict[str, Any]) -> dict[str, Any]:
    """Normalize an ffprobe result into the contract's source/enhanced shape."""
    summary = {
        "width": probe.get("video_width"),
        "height": probe.get("video_height"),
        "fps": probe.get("video_fps"),
        "duration_seconds": probe.get("duration_seconds"),
        "audio_streams": probe.get("audio_streams"),
    }
    return {key: value for key, value in summary.items() if value is not None}

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

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        """Run a local enhancement and validate the downloaded artifact.

        Downloads to a ``.partial.mp4`` sibling so an existing output is
        never overwritten by an invalid or interrupted run; only a validated
        result is moved into place with ``os.replace``.
        """
        started = time.perf_counter()
        error = self._validate_inputs(inputs)
        if error:
            return ToolResult(success=False, error=error)

        operation = str(inputs["operation"])
        source = Path(inputs["input_path"]).expanduser().resolve()
        output = Path(inputs["output_path"]).expanduser().resolve()

        client = self._client
        server_url = str(inputs.get("server_url") or "").strip()
        if server_url:
            if isinstance(client, ComfyUIClient):
                client = ComfyUIClient(server_url=server_url, capability="enhance")
            elif hasattr(client, "server_url"):
                client.server_url = server_url.rstrip("/")

        if not client.is_available():
            return ToolResult(success=False, error=client.unavailable_reason())
        if not source.is_file():
            return ToolResult(success=False, error=f"Source video not found: {source}")

        source_probe = self._probe_media(source)
        source_fps = _as_float(source_probe.get("video_fps"))

        # face_refine loads the source in place (VHS_LoadVideoPath accepts an
        # absolute path) and uploads both reference images; SeedVR2's
        # LoadVideo only resolves files in ComfyUI's input folder.
        try:
            ref_names: list[str] = []
            if operation == "face_refine":
                for reference in inputs.get("reference_image_paths") or []:
                    reference_path = Path(reference).expanduser().resolve()
                    if not reference_path.is_file():
                        return ToolResult(
                            success=False,
                            error=f"Reference image not found: {reference_path}",
                        )
                    ref_names.append(
                        client.upload_image(
                            reference_path,
                            f"{uuid.uuid4().hex}{reference_path.suffix}",
                        )
                    )
                source_name = str(source)
            else:
                source_name = client.upload_input_file(
                    source, f"{uuid.uuid4().hex}{source.suffix}"
                )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to upload {operation} inputs to ComfyUI: {exc}",
            )

        workflow_file = _WORKFLOW_FILES[operation]
        try:
            workflow = ComfyUIClient.load_workflow(_WORKFLOWS / workflow_file)
            patches = self._workflow_patches(
                operation,
                inputs,
                source_fps=source_fps or 0.0,
                source_name=source_name,
                ref_names=ref_names,
                output_prefix=f"om_enhance/{operation}/{uuid.uuid4().hex[:12]}",
            )
            # ffprobe unavailable: keep the bundled workflow's frame rate
            # rather than binding 0.0, and let validation skip.
            if operation == "face_refine" and not source_fps:
                patches["23"].pop("frame_rate", None)
            workflow = ComfyUIClient.patch_workflow(workflow, patches)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to build the {operation} workflow: {exc}",
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix(".partial.mp4")
        timeout = int(inputs.get("timeout_seconds") or 7200)

        try:
            paths = client.generate(
                workflow,
                output_node=_OUTPUT_NODE,
                dest=partial,
                timeout=timeout,
                interval=10,
            )
        except Exception as exc:
            _discard(partial)
            return ToolResult(
                success=False, error=f"ComfyUI {operation} failed: {exc}"
            )

        if not paths:
            _discard(partial)
            return ToolResult(
                success=False,
                error=f"ComfyUI {operation} produced no output artifact.",
            )

        downloaded = Path(paths[0])
        if not downloaded.is_file() or downloaded.stat().st_size == 0:
            _discard(partial)
            return ToolResult(
                success=False,
                error=(
                    f"ComfyUI {operation} returned an empty or missing "
                    f"artifact: {downloaded}"
                ),
            )

        output_probe = self._probe_media(downloaded)
        validation_error = self._validate_output_media(source_probe, output_probe)
        if validation_error:
            _discard(partial)
            return ToolResult(success=False, error=validation_error)

        ssim = self._compute_ssim(source, downloaded)
        warnings: list[str] = []
        if ssim is not None and ssim > _SSIM_UNCHANGED_THRESHOLD:
            warnings.append("output_virtually_unchanged")

        try:
            os.replace(downloaded, output)
        except OSError as exc:
            _discard(partial)
            return ToolResult(
                success=False,
                error=f"Could not move the enhanced video into place: {exc}",
            )

        models = self._merged_models(inputs)
        timing = dict(getattr(client, "last_timing", None) or {})
        timing["wall_s"] = round(time.perf_counter() - started, 3)
        result_data = {
            "operation": operation,
            "output_path": str(output),
            "source": _media_summary(source_probe),
            "enhanced": _media_summary(output_probe),
            "provenance": {
                "workflow": workflow_file,
                "workflow_hash_sha256": workflow_hash(workflow),
                "models": models,
                "parameters": self._provenance_parameters(operation, inputs),
                "source_asset_path": str(source),
            },
            "validation": {"ssim": ssim, "warnings": warnings},
            "timing": timing,
        }
        return ToolResult(
            success=True,
            data=result_data,
            artifacts=[str(output)],
            cost_usd=0.0,
            duration_seconds=round(time.perf_counter() - started, 2),
            seed=int(inputs.get("seed", 42)),
            model=models.get("seedvr2_dit") or models.get("unet"),
        )

    @staticmethod
    def _validate_output_media(
        source_probe: dict[str, Any], output_probe: dict[str, Any]
    ) -> str | None:
        """Compare output media against the source; ``None`` when it passes.

        An empty probe means ffprobe is unavailable — skip rather than
        misjudge the artifact.
        """
        if not source_probe or not output_probe:
            return None

        source_audio = source_probe.get("audio_streams")
        output_audio = output_probe.get("audio_streams")
        if (
            isinstance(source_audio, int)
            and isinstance(output_audio, int)
            and source_audio != output_audio
        ):
            return (
                "Output media validation failed: audio stream count changed "
                f"from {source_audio} to {output_audio}."
            )

        source_fps = _as_float(source_probe.get("video_fps"))
        output_fps = _as_float(output_probe.get("video_fps"))
        if not output_fps:
            return "Output media validation failed: the output has no video stream."
        if source_fps and abs(source_fps - output_fps) > _FPS_TOLERANCE:
            return (
                "Output media validation failed: frame rate changed from "
                f"{source_fps:g} to {output_fps:g} fps."
            )

        source_duration = _as_float(source_probe.get("duration_seconds"))
        output_duration = _as_float(output_probe.get("duration_seconds"))
        fps = source_fps or output_fps
        if source_duration and output_duration and fps:
            tolerance = 1.0 / fps
            if abs(source_duration - output_duration) > tolerance:
                return (
                    "Output media validation failed: duration changed from "
                    f"{source_duration:g}s to {output_duration:g}s "
                    f"(tolerance {tolerance:.3f}s = one frame at {fps:g} fps)."
                )
        return None

    @staticmethod
    def _provenance_parameters(
        operation: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Effective creative knobs recorded for reproducibility."""
        if operation == "face_refine":
            return {
                "denoise": inputs.get("denoise", 0.4),
                "face_select": inputs.get("face_select", "largest_face"),
                "identity_threshold": inputs.get("identity_threshold", 0.28),
                "face_denoise_multiplier": inputs.get(
                    "face_denoise_multiplier", 1.0
                ),
                "seed": inputs.get("seed", 42),
            }
        return {
            "resolution": inputs.get("resolution", 1080),
            "max_resolution": inputs.get("max_resolution", 0),
            "batch_size": inputs.get("batch_size", 5),
            "temporal_overlap": inputs.get("temporal_overlap", 3),
            "color_correction": inputs.get("color_correction", "lab"),
            "seed": inputs.get("seed", 42),
        }

    @staticmethod
    def _probe_media(path: Path) -> dict[str, Any]:
        """Read duration, frame rate and audio stream count with ffprobe.

        Returns ``{}`` when ffprobe is unavailable or cannot read the file so
        callers skip comparison instead of failing a valid artifact.
        """
        path = Path(path)
        if not path.is_file() or shutil.which("ffprobe") is None:
            return {}
        try:
            proc = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_streams",
                    "-show_format",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                return {}
            probe = json.loads(proc.stdout or "{}")
        except (OSError, ValueError, subprocess.SubprocessError):
            return {}

        info: dict[str, Any] = {"file_size_bytes": path.stat().st_size}
        duration = _as_float((probe.get("format") or {}).get("duration"))
        audio_streams = 0
        for stream in probe.get("streams") or []:
            codec_type = stream.get("codec_type")
            if codec_type == "video" and "video_fps" not in info:
                fps = _parse_frame_rate(
                    stream.get("avg_frame_rate")
                ) or _parse_frame_rate(stream.get("r_frame_rate"))
                if fps:
                    info["video_fps"] = fps
                width, height = stream.get("width"), stream.get("height")
                if isinstance(width, int):
                    info["video_width"] = width
                if isinstance(height, int):
                    info["video_height"] = height
                if duration is None:
                    duration = _as_float(stream.get("duration"))
            elif codec_type == "audio":
                audio_streams += 1
        if duration is not None:
            info["duration_seconds"] = round(duration, 3)
        info["audio_streams"] = audio_streams
        return info

    @staticmethod
    def _compute_ssim(source: Path, output: Path) -> float | None:
        """Whole-clip SSIM between source and output; ``None`` when unmeasurable."""
        if shutil.which("ffmpeg") is None:
            return None
        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-nostdin",
                    "-i",
                    str(source),
                    "-i",
                    str(output),
                    "-lavfi",
                    "ssim",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            return None
        match = re.search(r"All\:([0-9.]+)", proc.stderr or "")
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None
