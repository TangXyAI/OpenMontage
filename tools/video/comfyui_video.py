"""ComfyUI video generation via a local or remote ComfyUI server.

Supports text-to-video and image-to-video using WAN 2.2 14B with
4-step LightX2V LoRA acceleration.  Custom workflows are accepted
via the ``workflow_json`` input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools._comfyui.client import ComfyUIClient, ComfyUIError
from tools._comfyui.refmod_workflow import build_refmod_workflow
from tools._comfyui.metadata import (
    BUNDLED_MODEL_STACKS,
    COMFYUI_SETUP_OFFER,
    custom_input_provenance,
    missing_models_payload,
    model_stack,
    workflow_hash,
)
from tools._comfyui.h3_contracts import REFMOD_VIDEO_NODE_INPUT_REQUIREMENTS
from tools.video._shared import probe_output

_WORKFLOWS = Path(__file__).resolve().parent.parent / "_comfyui" / "workflows"

# Output node IDs in the bundled workflows
_T2V_OUTPUT_NODE = "16"
_I2V_OUTPUT_NODE = "108"

# Bundled HyperFlow H3 API workflows, one per supported operation.  The
# `14` SaveVideo node is shared by all four and is the output node.
_HYPERFLOW_WORKFLOWS = {
    "text_to_video": "hyperflow_int8_t2v_api.json",
    "image_to_video": "hyperflow_int8_i2v_api.json",
    "first_last_frame_to_video": "hyperflow_int8_flf2v_api.json",
    "reference_to_video": "hyperflow_int8_ref2v_api.json",
}
_HYPERFLOW_OUTPUT_NODE = "14"
_HYPERFLOW_REFMOD_REF2V_WORKFLOW = "hyperflow_int8_ref2v_refmod_api.json"

# Operations only the bundled HyperFlow H3 family can execute.  Every other
# family either has no workflow for them (WAN) or is text-to-video only
# (Partner Nodes), so `execute` rejects them up front instead of silently
# falling back to text_to_video or failing deep inside a workflow build.
_HYPERFLOW_ONLY_OPERATIONS = frozenset(
    {"first_last_frame_to_video", "reference_to_video"}
)

# Every operation the tool advertises, in workflow-key order.
_OPERATIONS = tuple(_HYPERFLOW_WORKFLOWS)

# Models required by the bundled WAN 2.2 workflows
_REQUIRED_MODELS_COMMON = [
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
]
_REQUIRED_MODELS_I2V = [
    *_REQUIRED_MODELS_COMMON,
    "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    "wan_2.1_vae.safetensors",
    "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
]
_REQUIRED_MODELS_T2V = [
    *_REQUIRED_MODELS_COMMON,
    "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
    "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
    "wan_2.1_vae.safetensors",
    "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
    "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
]

_RESOURCE_PROFILES = {
    "provider_floor": {
        "vram_mb": 8000,
        "ram_mb": 16000,
        "applies_to": (
            "ComfyUI provider availability and low-VRAM custom workflows. "
            "Actual requirements depend on workflow_json/workflow_path."
        ),
    },
    "bundled_wan22_14b_fp8": {
        "vram_mb": 16000,
        "ram_mb": 32000,
        "applies_to": (
            "Bundled WAN 2.2 14B FP8 T2V/I2V workflows. This is not a "
            "ComfyUI provider-wide requirement."
        ),
    },
    "low_vram_custom_workflows": {
        "vram_mb": "8000-12000",
        "ram_mb": "16000-32000",
        "examples": [
            "Wan 2.1 1.3B",
            "LTX-Video / LTXV FP8 or quantized workflows",
            "Wan 2.2 GGUF / quantized community workflows",
        ],
    },
}


class ComfyUIVideo(BaseTool):
    name = "comfyui_video"
    version = "0.2.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "comfyui"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU

    dependencies = []
    setup_offer = COMFYUI_SETUP_OFFER
    install_instructions = (
        "Start a ComfyUI server and set COMFYUI_SERVER_URL "
        "(default http://localhost:8188).\n"
        "Bundled local WAN requires WAN 2.2 models and LightX2V LoRAs. Local "
        "MiniMax H3 requires its official model stack and exported API workflow.\n"
        "Gemini Omni, Seedance 2.5, and MiniMax H3 Partner Nodes require a "
        "logged-in Comfy account, credits, and network access.\n"
        "Running a separate ComfyUI instance for video? Set COMFYUI_VIDEO_SERVER_URL "
        "instead -- it takes priority over COMFYUI_SERVER_URL for this tool only."
    )
    agent_skills = [
        "comfyui",
        "gemini-omni",
        "seedance-2-5",
        "minimax-h3",
        "ai-video-gen",
        "ltx2",
        "hyperflow-h3",
    ]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "seed": True,
        "reference_image": True,
        "first_last_frame_to_video": True,
        "reference_to_video": True,
        "custom_workflow": True,
        "custom_output_node": True,
        "offline": True,
        "gemini_omni_flash_partner_node": True,
        "seedance_2_5_partner_node": True,
        "minimax_h3_partner_node": True,
        "minimax_h3_local_weights": True,
    }
    best_for = [
        "local GPU video generation without API costs",
        "Blackwell / DGX Spark hardware where diffusers is unsupported",
        "image-to-video with WAN 2.2 14B (4-step accelerated)",
        "text-to-video with WAN 2.2 14B (4-step accelerated)",
        "custom low-VRAM ComfyUI workflows on 8GB-12GB GPUs",
        "ComfyUI Partner Node workflows for Gemini Omni Flash, Seedance 2.5, and MiniMax H3",
        "open-weight MiniMax H3 custom workflows with native stereo audio",
    ]
    not_good_for = [
        "setups without a running ComfyUI server",
        "CPU-only machines",
        "running the bundled WAN 2.2 14B FP8 workflows on GPUs below 16GB VRAM",
    ]
    fallback = "wan_video"
    fallback_tools = ["wan_video", "hunyuan_video", "ltx_video_local", "kling_video"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text prompt for video generation",
            },
            "operation": {
                "type": "string",
                "enum": [
                    "text_to_video",
                    "image_to_video",
                    "first_last_frame_to_video",
                    "reference_to_video",
                ],
                "default": "text_to_video",
            },
            "model_family": {
                "type": "string",
                "enum": [
                    "wan2.2",
                    "gemini_omni_flash",
                    "seedance_2.5",
                    "minimax_h3_api",
                    "minimax_h3_local",
                    "minimax_h3_hyperflow_local",
                    "ltx_2.5_local",
                ],
                "default": "wan2.2",
                "description": (
                    "Built-in execution family. The three *_api/hosted families use "
                    "ComfyUI Partner Nodes and credits; minimax_h3_local uses open weights "
                    "through a caller-supplied official/custom workflow, and "
                    "minimax_h3_hyperflow_local uses HyperFlow H3 open weights through a "
                    "caller-supplied API workflow."
                ),
            },
            "reference_image_path": {
                "type": "string",
                "description": "Local path to reference image (for image_to_video)",
            },
            "reference_image_url": {
                "type": "string",
                "description": "URL of reference image (for image_to_video, downloaded first)",
            },
            "first_frame_image_path": {
                "type": "string",
                "description": (
                    "Local first-frame image for first_last_frame_to_video "
                    "(HyperFlow H3 local)"
                ),
            },
            "last_frame_image_path": {
                "type": "string",
                "description": (
                    "Local last-frame image for first_last_frame_to_video "
                    "(HyperFlow H3 local)"
                ),
            },
            "reference_image_paths": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 2,
                "description": (
                    "Up to two local reference images for reference_to_video "
                    "(HyperFlow H3 local): first binds ref_image_0, second ref_image_1. "
                    "Two are required when no project RefMods are supplied."
                ),
            },
            "reference_videos": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": (
                    "Named local motion/video references for custom H3 Ref2VA graphs. "
                    "Bind each with workflow_bindings key reference_videos.<name>."
                ),
            },
            "refmod_assets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "asset_id",
                        "loader_name",
                        "concept_type",
                        "state",
                        "description",
                        "prompt_label",
                        "refmod_sha256",
                    ],
                    "properties": {
                        key: {"type": "string"}
                        for key in (
                            "asset_id",
                            "loader_name",
                            "concept_type",
                            "state",
                            "description",
                            "prompt_label",
                            "source_sha256",
                            "refmod_sha256",
                            "project_path",
                        )
                    },
                },
                "description": (
                    "Ordered project-approved RefMods for local MiniMax H3 Ref2VA. "
                    "Each entry includes asset_id, loader_name, concept_type, state, "
                    "description, and prompt_label."
                ),
            },
            "checkpoint_name": {
                "type": "string",
                "description": (
                    "Exact diffusion model filename in ComfyUI's diffusion_models/ "
                    "folder (HyperFlow H3 local). The loader is inferred from it."
                ),
            },
            "loader": {
                "type": "string",
                "enum": ["auto", "official_int8", "community_int8", "gguf"],
                "default": "auto",
                "description": (
                    "HyperFlow H3 loader class. auto infers from checkpoint_name; "
                    "official_int8 uses HyperFlowLoader, community_int8 uses "
                    "HyperFlowINT8Loader, gguf uses HyperFlowGGUFLoader."
                ),
            },
            "steps": {
                "type": "integer",
                "enum": [4, 6, 8],
                "default": 6,
                "description": "HyperFlow H3 sampling steps (4, 6, or 8).",
            },
            "width": {
                "type": "integer",
                "default": 832,
                "description": "T2V default 832, I2V default 640",
            },
            "height": {
                "type": "integer",
                "default": 480,
                "description": "T2V default 480, I2V default 640",
            },
            "num_frames": {
                "type": "integer",
                "default": 81,
                "description": "81 frames = 5s at 16fps",
            },
            "duration": {
                "type": "integer",
                "minimum": 3,
                "maximum": 30,
                "default": 5,
                "description": "Partner Node duration; bundled WAN still uses num_frames.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
                "default": "16:9",
            },
            "resolution": {
                "type": "string",
                "enum": ["480p", "720p", "768P", "2K"],
                "default": "720p",
            },
            "generate_audio": {"type": "boolean", "default": True},
            "seed": {"type": "integer", "description": "Random if omitted"},
            "output_path": {"type": "string", "description": "Where to save the video"},
            "server_url": {
                "type": "string",
                "description": "Optional ComfyUI server URL for this execution only.",
            },
            "comfyui_workspace": {
                "type": "string",
                "description": "Accessible ComfyUI workspace used to verify project RefMod loader copies.",
            },
            "workflow_json": {
                "type": "string",
                "description": "Optional full ComfyUI workflow JSON. Requires output_node.",
            },
            "workflow_bindings": {"type": "object", "description": "Map input names to lists of {node, input} targets in a custom workflow."},
            "resume_context": {"type": "object", "description": "Original provenance returned with a timed-out prompt."},
            "reference_images": {"type": "object", "description": "Named local image paths for custom workflow bindings."},
            "workflow_path": {
                "type": "string",
                "description": "Optional path to a ComfyUI workflow JSON file. Requires output_node.",
            },
            "output_node": {
                "type": "string",
                "description": "ComfyUI output node ID for custom workflow_json/workflow_path.",
            },
            "workflow_name": {
                "type": "string",
                "description": "Optional human-readable provenance label for a custom workflow.",
            },
            "workflow_model": {
                "type": "string",
                "description": "Optional model/provenance label for a custom workflow.",
            },
            "workflow_model_stack": {
                "type": "array",
                "description": (
                    "Optional provenance metadata for custom workflow dependencies. "
                    "Items should include name, role, quantization, scheduler, "
                    "and LoRA strengths when known."
                ),
                "items": {"type": "object"},
            },
            "timeout_seconds": {
                "type": "integer",
                "description": (
                    "How long to wait for the ComfyUI job to finish before giving up. "
                    "Default 3600s (1hr) covers slow/local GPUs and non-accelerated "
                    "custom workflows; raise it further for large frame counts or "
                    "high resolutions. On timeout the job is NOT cancelled server-side "
                    "and the error's data.prompt_id can be passed back via "
                    "resume_prompt_id to keep waiting without resubmitting."
                ),
            },
            "resume_prompt_id": {
                "type": "string",
                "description": (
                    "A prompt_id from a previous timed-out call (see error data on "
                    "timeout). Skips resubmission and just resumes waiting/downloading."
                ),
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2,
        ram_mb=16000,
        vram_mb=8000,
        disk_mb=2000,
        network_required=False,
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = [
        "prompt",
        "operation",
        "model_family",
        "checkpoint_name",
        "width",
        "height",
        "num_frames",
        "seed",
        "reference_image_path",
        "reference_image_paths",
        "reference_videos",
        "first_frame_image_path",
        "last_frame_image_path",
        "refmod_assets",
        "server_url",
        "workflow_json",
        "workflow_path",
        "workflow_bindings",
        "reference_images",
        "output_node",
        "workflow_model",
        "workflow_model_stack",
    ]
    side_effects = ["writes video file to output_path"]
    user_visible_verification = [
        "Watch generated clip for motion coherence and artifacts"
    ]

    def __init__(self) -> None:
        self._client = ComfyUIClient(capability="video")
        self._last_progress_log = 0.0

    def _log_progress(self, data: dict) -> None:
        """Print a throttled progress line for long video renders.

        Video jobs can run for tens of minutes; without this the process
        looks hung. Throttled to once per 10s since ComfyUI pushes a
        ``progress`` event per sampling step, which would otherwise flood
        stdout on fast GPUs.
        """
        now = time.monotonic()
        if now - self._last_progress_log < 10:
            return
        self._last_progress_log = now
        value, max_value = data.get("value"), data.get("max")
        if value is not None and max_value:
            print(f"[comfyui_video] step {value}/{max_value}")

    def get_status(self) -> ToolStatus:
        if not self._client.is_available():
            return ToolStatus.UNAVAILABLE
        statuses = self.operation_statuses()
        if any(status == "available" for status in statuses.values()):
            return ToolStatus.AVAILABLE
        if statuses:
            return ToolStatus.DEGRADED
        return ToolStatus.UNAVAILABLE

    def operation_statuses(self) -> dict[str, str]:
        """Return per-operation readiness for selector routing and preflight."""
        if not self._client.is_available():
            return {operation: "unavailable" for operation in _OPERATIONS}

        _, missing_t2v = self._client.check_models(_REQUIRED_MODELS_T2V)
        _, missing_i2v = self._client.check_models(_REQUIRED_MODELS_I2V)
        statuses = {
            "text_to_video": "available" if not missing_t2v else "degraded",
            "image_to_video": "available" if not missing_i2v else "degraded",
        }
        # HyperFlow readiness is bundled-workflow presence, not WAN model
        # discovery: the caller supplies checkpoint_name and the loader.
        for operation in _HYPERFLOW_ONLY_OPERATIONS:
            workflow_file = _WORKFLOWS / _HYPERFLOW_WORKFLOWS[operation]
            statuses[operation] = (
                "available" if workflow_file.is_file() else "degraded"
            )
        return statuses

    def is_operation_available(self, operation: str) -> bool:
        if operation not in _OPERATIONS:
            return False
        return self.operation_statuses().get(operation) == "available"

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["operation_statuses"] = self.operation_statuses()
        info["resource_profiles"] = _RESOURCE_PROFILES
        info["setup_offer"] = self.setup_offer
        info["bundled_model_stacks"] = {
            "text_to_video": BUNDLED_MODEL_STACKS["wan22-t2v-4step"],
            "image_to_video": BUNDLED_MODEL_STACKS["wan22-i2v-4step"],
        }
        info["resource_profile_note"] = (
            "The top-level resource_profile is a ComfyUI provider floor, not a "
            "promise that every workflow fits 8GB VRAM. Bundled WAN 2.2 14B FP8 "
            "workflows recommend 16GB VRAM; custom low-VRAM workflows can target "
            "8GB-12GB depending on model, quantization, resolution, and frame count."
        )
        info["execution_modes"] = {
            "wan2.2": {
                "hosted": False,
                "network_required": False,
                "cost": "local compute",
            },
            "minimax_h3_local": {
                "hosted": False,
                "network_required": False,
                "cost": "local compute",
                "readiness": "unknown",
            },
            "gemini_omni_flash": {
                "hosted": True,
                "network_required": True,
                "billing": "ComfyUI Partner Node credits",
            },
            "seedance_2.5": {
                "hosted": True,
                "network_required": True,
                "billing": "ComfyUI Partner Node credits",
            },
            "minimax_h3_api": {
                "hosted": True,
                "network_required": True,
                "billing": "ComfyUI Partner Node credits",
            },
        }
        return info

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        family = str(inputs.get("model_family", "wan2.2"))
        duration = float(inputs.get("duration", 5))
        if family == "gemini_omni_flash":
            return round(0.146 * duration, 4)
        if family == "seedance_2.5":
            rate = 0.1483 if inputs.get("resolution", "720p") == "480p" else 0.3333
            return round(rate * duration, 4)
        if family == "minimax_h3_api":
            rate = 0.1287 if inputs.get("resolution", "768P") == "768P" else 0.1859
            return round(rate * duration, 4)
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        operation = inputs.get("operation", "text_to_video")
        if operation == "image_to_video":
            return 210.0  # ~3.5 min
        return 240.0  # ~4 min

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        resume_id = inputs.get("resume_prompt_id")
        resume_context = inputs.get("resume_context") or {}
        if resume_id and resume_context and resume_context.get("prompt_id") != resume_id:
            return ToolResult(success=False, error="resume_context prompt_id does not match resume_prompt_id")
        if resume_id and resume_context and inputs.get("output_node") and str(inputs["output_node"]) != resume_context.get("output_node"):
            return ToolResult(success=False, error="output_node does not match the original resume_context")
        custom_workflow = bool(
            inputs.get("workflow_json") or inputs.get("workflow_path")
        )
        model_family = str(inputs.get("model_family", "wan2.2"))
        requested_operation = inputs.get("operation", "text_to_video")
        requested_server_url = inputs.get("server_url")
        if resume_id:
            resumed_server_url = resume_context.get("server_url")
            if (
                requested_server_url
                and resumed_server_url
                and str(requested_server_url).rstrip("/")
                != str(resumed_server_url).rstrip("/")
            ):
                return ToolResult(
                    success=False,
                    error=(
                        "server_url does not match the ComfyUI server that owns "
                        "this prompt_id"
                    ),
                )
            requested_server_url = requested_server_url or resumed_server_url
        refmod_assets = inputs.get("refmod_assets") or []
        if refmod_assets and not resume_id:
            if requested_operation == "first_last_frame_to_video":
                return ToolResult(
                    success=False,
                    error=(
                        "Project RefMods require H3 Ref2VA and cannot be combined "
                        "with FL2VA first/last-frame conditioning."
                    ),
                )
            if model_family not in {
                "minimax_h3_local",
                "minimax_h3_hyperflow_local",
            }:
                return ToolResult(
                    success=False,
                    error=(
                        "Supplied local RefMod bindings require a local MiniMax H3 "
                        "Ref2VA route; hosted H3 and other model families cannot use "
                        "local RefMod nodes."
                    ),
                )
            if requested_operation != "reference_to_video":
                return ToolResult(
                    success=False,
                    error="Local RefMods are supported only for H3 Ref2VA reference_to_video.",
                )
        if (
            requested_operation in _HYPERFLOW_ONLY_OPERATIONS
            and model_family != "minimax_h3_hyperflow_local"
            and not (model_family == "minimax_h3_local" and custom_workflow)
        ):
            return ToolResult(
                success=False,
                error=(
                    f"Operation {requested_operation!r} is only supported by "
                    "model_family='minimax_h3_hyperflow_local'. "
                    f"Got model_family={model_family!r}; use the HyperFlow "
                    "family or choose text_to_video/image_to_video."
                ),
            )
        client = self._client
        if requested_server_url:
            client = ComfyUIClient(
                server_url=str(requested_server_url), capability="video"
            )
        partner_nodes = {
            "gemini_omni_flash": "GeminiVideoOmni",
            "seedance_2.5": "ByteDance2TextToVideoNode",
            "minimax_h3_api": "MinimaxHailuo03TextToVideoNode",
        }
        if model_family == "ltx_2.5_local" and not custom_workflow and not resume_id:
            return ToolResult(
                success=False,
                error="LTX-2.5 local requires an installed model stack and an exported ComfyUI API workflow via workflow_path/workflow_json plus output_node. No older LTX or WAN fallback is performed.",
                data={"model": "LTX-2.5", "setup_required": True},
            )
        if model_family == "minimax_h3_local" and not custom_workflow and not resume_id:
            return ToolResult(
                success=False,
                data={
                    "provider": "comfyui",
                    "model": "MiniMax-H3",
                    "workflow_template": "https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_t2v.json",
                    "model_stack": BUNDLED_MODEL_STACKS["minimax-h3-local"],
                },
                error=(
                    "minimax_h3_local requires the official MiniMax H3 ComfyUI workflow "
                    "exported in API format via workflow_json/workflow_path plus output_node."
                ),
            )
        if (
            model_family == "minimax_h3_hyperflow_local"
            and not custom_workflow
            and not inputs.get("checkpoint_name")
            and not resume_id
        ):
            return ToolResult(
                success=False,
                data={
                    "provider": "comfyui",
                    "model": "MiniMax-H3 HyperFlow",
                    "setup_required": True,
                    "workflow_templates": {
                        "t2v": "tools/_comfyui/workflows/hyperflow_int8_t2v_api.json",
                        "i2v": "tools/_comfyui/workflows/hyperflow_int8_i2v_api.json",
                        "flf2v": "tools/_comfyui/workflows/hyperflow_int8_flf2v_api.json",
                        "ref2v": "tools/_comfyui/workflows/hyperflow_int8_ref2v_api.json",
                    },
                    "model_stack": BUNDLED_MODEL_STACKS["minimax-h3-hyperflow-local"],
                },
                error=(
                    "minimax_h3_hyperflow_local requires checkpoint_name or an API-format "
                    "workflow via workflow_json/workflow_path plus output_node."
                ),
            )
        if (
            model_family in partner_nodes
            and inputs.get("operation", "text_to_video") != "text_to_video"
        ):
            return ToolResult(
                success=False,
                error=(
                    f"Built-in {model_family} Partner Node execution currently supports "
                    "text_to_video; use an official ComfyUI custom workflow for other modes."
                ),
            )
        if custom_workflow and not inputs.get("output_node"):
            return ToolResult(
                success=False,
                error=(
                    "Custom ComfyUI workflows require output_node so OpenMontage "
                    "knows which ComfyUI node to download artifacts from."
                ),
            )

        if not client.is_available():
            return ToolResult(
                success=False,
                error=client.unavailable_reason(),
            )
        if refmod_assets and not resume_id:
            required_refmod_nodes = (
                "MiniMaxH3RefModsLoader",
                "MiniMaxH3RefModTextEncode",
                "MiniMaxH3ReferenceToVideo",
                "BasicGuider",
            )
            missing_refmod_nodes = [
                node for node in required_refmod_nodes if not client.has_node(node)
            ]
            if missing_refmod_nodes:
                return ToolResult(
                    success=False,
                    error=(
                        "Local H3 RefMod execution is blocked; the selected ComfyUI "
                        "server is missing nodes: "
                        + ", ".join(missing_refmod_nodes)
                    ),
                )
            missing_refmod_inputs = []
            try:
                for node, required_inputs in REFMOD_VIDEO_NODE_INPUT_REQUIREMENTS.items():
                    missing_inputs = client.check_node_inputs(node, required_inputs)
                    if missing_inputs:
                        missing_refmod_inputs.append(
                            f"{node} ({', '.join(missing_inputs)})"
                        )
            except ComfyUIError as exc:
                return ToolResult(
                    success=False,
                    error=f"Local H3 RefMod node input validation failed: {exc}",
                )
            if missing_refmod_inputs:
                return ToolResult(
                    success=False,
                    error=(
                        "Local H3 RefMod execution is blocked; the selected ComfyUI "
                        "server has incompatible node inputs: "
                        + ", ".join(missing_refmod_inputs)
                    ),
                )
            loader_error = self._verify_refmod_loader_copies(
                refmod_assets, inputs.get("comfyui_workspace")
            )
            if loader_error:
                return ToolResult(success=False, error=loader_error)

        operation = inputs.get("operation", "text_to_video")

        if not custom_workflow and model_family == "wan2.2" and not resume_id:
            required = (
                _REQUIRED_MODELS_I2V
                if operation == "image_to_video"
                else _REQUIRED_MODELS_T2V
            )
            _, missing = client.check_models(required)
            if missing:
                workflow_key = (
                    "wan22-i2v-4step"
                    if operation == "image_to_video"
                    else "wan22-t2v-4step"
                )
                return ToolResult(
                    success=False,
                    data=missing_models_payload(
                        missing,
                        workflow_key=workflow_key,
                        workflow_name=f"{workflow_key}.json",
                        operation=operation,
                    ),
                    error=(
                        f"ComfyUI server is running but missing models for {operation}: "
                        f"{', '.join(missing)}.\n"
                        f"See data.missing_models for destination hints and download URLs."
                    ),
                )
        start = time.time()
        seed = resume_context.get("seed") if resume_id else (inputs.get("seed") if inputs.get("seed") is not None else ComfyUIClient.random_seed())
        output_path = Path(
            inputs.get("output_path", f"comfyui_video_{operation}_{seed}.mp4")
        )

        hyperflow_meta: dict[str, Any] = {}
        try:
            if resume_id:
                output_node = str(inputs.get("output_node") or resume_context.get("output_node") or "")
                if not output_node:
                    raise ComfyUIError("Resuming a video requires the original output_node")
                workflow = {}
            elif custom_workflow:
                workflow = self._load_custom_workflow(inputs)
                if model_family == "minimax_h3_local" and any(
                    node.get("class_type") in set(partner_nodes.values())
                    for node in workflow.values() if isinstance(node, dict)
                ):
                    raise ComfyUIError("Local MiniMax H3 workflow contains a hosted ComfyUI Partner Node")
                workflow_bindings = inputs.get("workflow_bindings", {})
                binding_values = {**inputs, "seed": seed}
                reference_videos = dict(inputs.get("reference_videos") or {})
                for parameter in workflow_bindings:
                    if not parameter.startswith("reference_videos."):
                        continue
                    reference_key = parameter.split(".", 1)[1]
                    reference_path = reference_videos.get(reference_key)
                    if not reference_path or not Path(reference_path).is_file():
                        raise ComfyUIError(
                            f"Native motion reference {reference_key!r} is missing"
                        )
                    reference_path = Path(reference_path)
                    suffix = reference_path.suffix.lower()
                    mime_type = {
                        ".mp4": "video/mp4",
                        ".mov": "video/quicktime",
                        ".webm": "video/webm",
                        ".mkv": "video/x-matroska",
                        ".avi": "video/x-msvideo",
                    }.get(suffix, "application/octet-stream")
                    upload_name = (
                        "om_motion_"
                        + hashlib.sha256(
                            f"{output_path.stem}:{reference_key}".encode("utf-8")
                        ).hexdigest()[:16]
                        + suffix
                    )
                    reference_videos[reference_key] = client.upload_input_file(
                        reference_path, upload_name, mime_type
                    )
                    binding_values[parameter] = reference_videos[reference_key]
                if reference_videos:
                    binding_values["reference_videos"] = reference_videos
                workflow = client.bind_workflow(
                    workflow, workflow_bindings, binding_values
                )
                if refmod_assets:
                    workflow, ordered_asset_ids = build_refmod_workflow(
                        workflow, refmod_assets, operation
                    )
                    hyperflow_meta["refmod_assets"] = self._refmod_provenance(
                        refmod_assets, ordered_asset_ids
                    )
                    hyperflow_meta["refmod_asset_ids"] = ordered_asset_ids
                    hyperflow_meta["refmod_workflow"] = "MiniMaxH3RefModApply"
                output_node = str(inputs["output_node"])
            elif model_family in partner_nodes:
                node_class = partner_nodes[model_family]
                if not client.has_node(node_class):
                    raise ComfyUIError(
                        f"ComfyUI server does not expose {node_class}; update ComfyUI "
                        "and enable Partner Nodes. These are hosted API nodes, not offline models."
                    )
                workflow, output_node = self._build_partner_t2v(
                    inputs, seed, output_path, model_family
                )
            elif model_family == "minimax_h3_hyperflow_local":
                workflow, output_node, hyperflow_meta = self._build_hyperflow(
                    inputs, seed, output_path, client=client
                )
            elif operation == "image_to_video":
                workflow, output_node = self._build_i2v(
                    inputs, seed, output_path, client=client
                )
            else:
                workflow, output_node = self._build_t2v(inputs, seed, output_path)

            if refmod_assets and not resume_id:
                required_models = self._workflow_model_files(workflow)
                _, missing_models = client.check_models(required_models)
                if missing_models:
                    raise ComfyUIError(
                        "Local H3 RefMod execution is blocked; the selected ComfyUI "
                        "server is missing models: " + ", ".join(missing_models)
                    )

            provenance = (resume_context.get("workflow_provenance") or {"source": "unknown_resumed_task", "prompt_id": resume_id, "output_node": output_node}
                          if resume_id else self._workflow_provenance(
                              inputs, custom_workflow, output_node, operation, workflow, model_family))
            if hyperflow_meta:
                provenance.update(hyperflow_meta)
            paths = client.generate(
                workflow,
                output_node=output_node,
                dest=output_path,
                timeout=inputs.get("timeout_seconds", 3600),
                interval=10,
                resume_prompt_id=inputs.get("resume_prompt_id"),
                on_progress=self._log_progress,
            )

        except ComfyUIError as exc:
            data = {"prompt_id": exc.prompt_id} if exc.prompt_id else {}
            if exc.prompt_id and "provenance" in locals():
                data["resume_context"] = (resume_context if resume_id else {
                    "prompt_id": exc.prompt_id, "workflow_provenance": provenance,
                    "seed": seed, "model": self._model_name(inputs, custom_workflow),
                    "prompt": inputs.get("prompt"), "output_node": output_node,
                    "hosted": model_family in partner_nodes and not custom_workflow,
                    "server_url": client.server_url,
                })
            if exc.prompt_id:
                error_msg = (
                    f"{exc}\n\nThis job was NOT cancelled and is very likely still "
                    f"running server-side. To recover it without resubmitting, call "
                    f"execute() again with resume_prompt_id={exc.prompt_id!r} "
                    f"(and a longer timeout_seconds if it needs more time), or poll "
                    f"GET {client.server_url}/history/{exc.prompt_id} directly."
                )
            else:
                error_msg = str(exc)
            return ToolResult(success=False, error=error_msg, data=data)
        except Exception as exc:
            return ToolResult(
                success=False, error=f"ComfyUI video generation failed: {exc}"
            )

        model_name = (resume_context.get("model") or "unknown-resumed-task") if resume_id else self._model_name(inputs, custom_workflow)
        partner_execution = model_family in partner_nodes and not custom_workflow and not resume_id
        result_data: dict[str, Any] = {
            "provider": "comfyui",
            "model": model_name,
            "prompt": resume_context.get("prompt") if resume_id else inputs["prompt"],
            "operation": operation,
            "output": str(paths[0]),
            "format": "mp4",
            "workflow_provenance": provenance,
            "hosted": resume_context.get("hosted") if resume_id else partner_execution,
            "network_required": resume_context.get("hosted") if resume_id else partner_execution,
        }
        if partner_execution:
            result_data.update(
                {
                    "duration_seconds": int(inputs.get("duration", 5)),
                    "fps": 24,
                    "aspect_ratio": inputs.get("aspect_ratio", "16:9"),
                    "resolution": inputs.get("resolution", "720p"),
                    "billing": "ComfyUI Partner Node credits",
                }
            )
        elif not resume_id:
            if model_family == "minimax_h3_hyperflow_local":
                width = inputs.get("width", 960)
                height = inputs.get("height", 544)
                num_frames = inputs.get("num_frames", 73)
            else:
                width = inputs.get("width", 832 if operation == "text_to_video" else 640)
                height = inputs.get("height", 480 if operation == "text_to_video" else 640)
                num_frames = inputs.get("num_frames", 81)
            result_data.update(
                {
                    "width": width,
                    "height": height,
                    "num_frames": num_frames,
                    "fps": 16,
                    "duration_seconds": round(num_frames / 16, 2),
                }
            )
        wall = round(time.time() - start, 3)
        comfy_timing = dict(getattr(client, "last_timing", None) or {})
        exec_s = comfy_timing.get("comfy_prompt_exec_s")
        overhead = wall
        if isinstance(exec_s, (int, float)):
            overhead = round(max(0.0, wall - float(exec_s)), 3)
        result_data["timing"] = {
            **comfy_timing,
            "client_overhead_s": overhead,
            "wall_s": wall,
        }


        result_data.update(self._probe_media(paths[0]))
        return ToolResult(
            success=True,
            data=result_data,
            artifacts=[str(p) for p in paths],
            cost_usd=0.0 if resume_id else self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            seed=seed,
            model=model_name,
        )

    # ------------------------------------------------------------------
    # Workflow builders
    # ------------------------------------------------------------------

    def _build_t2v(
        self, inputs: dict[str, Any], seed: int, output_path: Path
    ) -> tuple[dict, str]:
        width = inputs.get("width", 832)
        height = inputs.get("height", 480)
        num_frames = inputs.get("num_frames", 81)

        workflow = ComfyUIClient.load_workflow(_WORKFLOWS / "wan22-t2v-4step.json")
        workflow = ComfyUIClient.patch_workflow(
            workflow,
            {
                "2": {"text": inputs["prompt"]},
                # `length` is the frame count, `batch_size` is how many separate
                # clips to make. Node 11 used to be an EmptyLatentImage with
                # batch_size=num_frames, which asks for 81 unrelated images
                # rather than one 81-frame video: the mp4 has the right frame
                # count and duration and passes ffprobe, but strobes. WAN 2.2
                # needs a temporal video latent, as ComfyUI's own
                # video_wan2_2_14B_t2v template uses.
                "11": {
                    "width": width,
                    "height": height,
                    "length": num_frames,
                    "batch_size": 1,
                },
                "12": {"noise_seed": seed},
                "16": {"filename_prefix": output_path.stem},
            },
        )
        return workflow, _T2V_OUTPUT_NODE

    def _build_i2v(
        self,
        inputs: dict[str, Any],
        seed: int,
        output_path: Path,
        *,
        client: ComfyUIClient | None = None,
    ) -> tuple[dict, str]:
        client = client or self._client
        width = inputs.get("width", 640)
        height = inputs.get("height", 640)
        num_frames = inputs.get("num_frames", 81)

        # Resolve reference image
        ref_path = inputs.get("reference_image_path")
        ref_url = inputs.get("reference_image_url")

        if ref_url and not ref_path:
            # Download to a temp location
            resp = requests.get(ref_url, timeout=60)
            resp.raise_for_status()
            ref_path = str(output_path.with_suffix(".ref.png"))
            Path(ref_path).parent.mkdir(parents=True, exist_ok=True)
            Path(ref_path).write_bytes(resp.content)

        if not ref_path:
            raise ComfyUIError(
                "image_to_video requires reference_image_path or reference_image_url"
            )

        # Upload to ComfyUI
        upload_name = f"om_{output_path.stem}.png"
        server_name = client.upload_image(Path(ref_path), upload_name)

        workflow = ComfyUIClient.load_workflow(_WORKFLOWS / "wan22-i2v-4step.json")
        workflow = ComfyUIClient.patch_workflow(
            workflow,
            {
                "93": {"text": inputs["prompt"]},
                "97": {"image": server_name},
                "98": {"width": width, "height": height, "length": num_frames},
                "86": {"noise_seed": seed},
                "108": {"filename_prefix": output_path.stem},
            },
        )
        return workflow, _I2V_OUTPUT_NODE

    @staticmethod
    def _normalize_hyperflow_loader(
        workflow: dict, checkpoint_name: str | None, loader: str
    ) -> dict:
        """Patch node 1 to the loader class that matches ``checkpoint_name``.

        The bundled API workflows ship with the community ``HyperFlowINT8Loader``
        and the BennyDaBall INT8 filenames. A user may instead point
        ``checkpoint_name`` at the official INT8 file or a GGUF quant, so the
        loader class and its inputs must be rewritten before submission.
        """
        name = str(checkpoint_name or "")
        lowered = name.lower()
        loader = str(loader or "auto").lower()

        if loader == "gguf" or lowered.endswith(".gguf") or ".gguf" in lowered:
            class_type = "HyperFlowGGUFLoader"
            inputs: dict[str, Any] = {"unet_name": name, "weights_in": "auto"}
        elif loader == "official_int8" or "14b-int8_convrot" in lowered:
            class_type = "HyperFlowLoader"
            inputs = {"unet_name": name}
        else:
            class_type = "HyperFlowINT8Loader"
            inputs = {"unet_name": name, "patcher": "legacy"}

        normalized = copy.deepcopy(workflow)
        if "1" not in normalized:
            raise ValueError("HyperFlow workflow is missing loader node 1")
        normalized["1"]["class_type"] = class_type
        normalized["1"]["inputs"] = inputs
        return normalized

    def _build_hyperflow(
        self,
        inputs: dict[str, Any],
        seed: int,
        output_path: Path,
        *,
        client: ComfyUIClient | None = None,
    ) -> tuple[dict, str, dict]:
        """Build a bundled HyperFlow H3 workflow and bind its inputs.

        Returns ``(workflow, output_node, metadata)`` where ``metadata`` holds
        the selected loader/checkpoint for provenance.
        """
        client = client or self._client
        operation = str(inputs.get("operation", "text_to_video"))
        workflow_file = _HYPERFLOW_WORKFLOWS.get(operation)
        if workflow_file is None:
            raise ValueError(
                f"minimax_h3_hyperflow_local does not support operation {operation!r}"
            )
        checkpoint_name = inputs.get("checkpoint_name")
        if not checkpoint_name:
            raise ValueError("minimax_h3_hyperflow_local requires checkpoint_name")
        loader = str(inputs.get("loader", "auto"))
        refmod_assets = inputs.get("refmod_assets") or []
        if operation == "reference_to_video" and refmod_assets:
            workflow_file = _HYPERFLOW_REFMOD_REF2V_WORKFLOW

        workflow = ComfyUIClient.load_workflow(_WORKFLOWS / workflow_file)
        workflow = self._normalize_hyperflow_loader(workflow, checkpoint_name, loader)

        bindings: dict[str, list[dict[str, str]]] = {
            "prompt": [{"node": "5", "input": "prompt"}],
            "width": [{"node": "5", "input": "width"}],
            "height": [{"node": "5", "input": "height"}],
            "num_frames": [{"node": "5", "input": "length"}],
            "steps": [{"node": "6", "input": "steps"}],
            "seed": [{"node": "8", "input": "noise_seed"}],
            "filename_prefix": [{"node": "14", "input": "filename_prefix"}],
        }
        values: dict[str, Any] = {
            "prompt": inputs["prompt"],
            "width": inputs.get("width", 960),
            "height": inputs.get("height", 544),
            "num_frames": inputs.get("num_frames", 73),
            "steps": inputs.get("steps", 6),
            "seed": seed,
            "filename_prefix": output_path.stem,
        }

        refmod_provenance: list[dict[str, Any]] = []
        refmod_asset_ids: list[str] = []
        if operation == "image_to_video":
            reference = inputs.get("reference_image_path") or inputs.get("first_frame_image_path")
            if not reference:
                raise ValueError(
                    "image_to_video requires reference_image_path or first_frame_image_path"
                )
            bindings["reference_image_path"] = [{"node": "20", "input": "image"}]
            values["reference_image_path"] = reference
        elif operation == "first_last_frame_to_video":
            first = inputs.get("first_frame_image_path")
            last = inputs.get("last_frame_image_path")
            if not (first and last):
                raise ValueError(
                    "first_last_frame_to_video requires first_frame_image_path and "
                    "last_frame_image_path"
                )
            bindings["reference_images.first_frame"] = [{"node": "20", "input": "image"}]
            bindings["reference_images.last_frame"] = [{"node": "21", "input": "image"}]
            values["reference_images"] = {"first_frame": first, "last_frame": last}
        elif operation == "reference_to_video":
            references = inputs.get("reference_image_paths") or []
            if len(references) > 2:
                raise ValueError("reference_to_video accepts at most two native reference images")
            if not refmod_assets and len(references) < 2:
                raise ValueError(
                    "reference_to_video requires two reference_image_paths"
                )
            refmod_bindings: dict[str, Any] = {}
            for index, (input_name, node_id) in enumerate(
                (("ref_image_0", "20"), ("ref_image_1", "21"))
            ):
                if index < len(references):
                    refmod_bindings[input_name] = references[index]
                    bindings[f"reference_images.{input_name}"] = [
                        {"node": node_id, "input": "image"}
                    ]
                else:
                    workflow["5"]["inputs"].pop(
                        f"ref_images.{input_name}", None
                    )
                    workflow.pop(node_id, None)
            if refmod_bindings:
                values["reference_images"] = refmod_bindings

        workflow = client.bind_workflow(workflow, bindings, values)
        if operation == "reference_to_video" and refmod_assets:
            workflow, ordered_asset_ids = build_refmod_workflow(
                workflow, refmod_assets, operation
            )
            refmod_asset_ids = ordered_asset_ids
            refmod_provenance = self._refmod_provenance(
                refmod_assets, ordered_asset_ids
            )
        metadata = {
            "workflow": workflow_file,
            "checkpoint_name": checkpoint_name,
            "loader": workflow["1"]["class_type"],
        }
        if refmod_provenance:
            metadata["refmod_assets"] = refmod_provenance
            metadata["refmod_asset_ids"] = refmod_asset_ids
            metadata["refmod_workflow"] = "MiniMaxH3RefModApply"
        return workflow, _HYPERFLOW_OUTPUT_NODE, metadata

    @staticmethod
    def _verify_refmod_loader_copies(
        refs: list[dict[str, Any]], workspace_path: str | Path | None
    ) -> str | None:
        if not workspace_path:
            return "Project RefMods require the selected comfyui_workspace path"
        workspace = Path(workspace_path).resolve()
        model_root = (workspace / "models" / "refmods").resolve()
        for ref in refs:
            if not isinstance(ref, dict):
                return "RefMod binding must be an asset descriptor object"
            loader_name = str(ref.get("loader_name", "")).replace("\\", "/")
            expected_hash = ref.get("refmod_sha256")
            if not loader_name or not isinstance(expected_hash, str):
                return f"RefMod binding {ref.get('asset_id', '<unknown>')} is missing its loader name or hash"
            loader_path = (model_root / f"{loader_name}.safetensors").resolve()
            if not loader_path.is_relative_to(model_root):
                return f"RefMod loader path leaves the selected models/refmods folder: {loader_name}"
            if not loader_path.is_file():
                return f"RefMod loader copy is missing for {ref.get('asset_id', loader_name)}"
            digest = hashlib.sha256(loader_path.read_bytes()).hexdigest()
            if digest != expected_hash:
                return f"RefMod loader copy hash mismatch for {ref.get('asset_id', loader_name)}"
        return None

    @staticmethod
    def _refmod_provenance(
        refs: list[dict[str, Any]], ordered_asset_ids: list[str]
    ) -> list[dict[str, Any]]:
        by_id = {str(ref.get("asset_id")): ref for ref in refs if isinstance(ref, dict)}
        return [
            {
                key: by_id[asset_id][key]
                for key in (
                    "asset_id",
                    "loader_name",
                    "concept_type",
                    "state",
                    "prompt_label",
                    "source_sha256",
                    "refmod_sha256",
                )
                if key in by_id[asset_id]
            }
            for asset_id in ordered_asset_ids
        ]

    @staticmethod
    def _workflow_model_files(workflow: dict[str, Any]) -> list[str]:
        """Collect model filenames embedded in the selected API graph."""
        fields = {
            "unet_name",
            "ckpt_name",
            "clip_name",
            "vae_name",
            "audio_vae_name",
            "model_name",
        }
        names = {
            value
            for node in workflow.values()
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict)
            for key, value in node["inputs"].items()
            if key in fields and isinstance(value, str) and value.strip()
        }
        return sorted(names)

    @staticmethod
    def _probe_media(path: Path) -> dict[str, Any]:
        """Measure the downloaded clip instead of trusting the request.

        Custom workflows set their own size, frame count and frame rate, so
        the request values (WAN defaults when omitted) can be wrong. When
        ffprobe cannot read the file, the request values are kept and the
        result is flagged so callers know they were not measured.
        """
        probed = probe_output(path) if path.is_file() else {}
        width = probed.get("video_width")
        height = probed.get("video_height")
        fps = probed.get("video_fps")
        duration = probed.get("duration_seconds")
        if not (width and height and fps and duration):
            warning = (
                f"Could not probe {path} with ffprobe; the reported media "
                "metadata comes from the request, not the output file."
            )
            print(f"[comfyui_video] {warning}")
            return {"metadata_source": "requested", "metadata_warning": warning}
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "num_frames": probed.get("video_num_frames") or round(duration * fps),
            "duration_seconds": duration,
            "metadata_source": "ffprobe",
        }

    @staticmethod
    def _load_custom_workflow(inputs: dict[str, Any]) -> dict:
        if inputs.get("workflow_json"):
            return json.loads(inputs["workflow_json"])
        return ComfyUIClient.load_workflow(Path(inputs["workflow_path"]))

    @staticmethod
    def _model_name(inputs: dict[str, Any], custom_workflow: bool) -> str:
        family = str(inputs.get("model_family", "wan2.2"))
        if not custom_workflow:
            if family == "minimax_h3_hyperflow_local":
                return inputs.get("workflow_model") or "MiniMax-H3 HyperFlow (local ComfyUI workflow)"
            return {
                "wan2.2": "wan2.2-14b-fp8-4step",
                "gemini_omni_flash": "gemini-omni-flash-preview (ComfyUI Partner Node)",
                "seedance_2.5": "Seedance 2.5 (ComfyUI Partner Node)",
                "minimax_h3_api": "MiniMax-H3 (ComfyUI Partner Node)",
            }.get(family, "custom-comfyui-model")
        if family == "ltx_2.5_local":
            return inputs.get("workflow_model") or "LTX-2.5 (local ComfyUI workflow)"
        if family == "minimax_h3_local":
            return inputs.get("workflow_model") or "MiniMax-H3 (local ComfyUI workflow)"
        if family == "minimax_h3_hyperflow_local":
            return inputs.get("workflow_model") or "MiniMax-H3 HyperFlow (local ComfyUI workflow)"
        return (
            inputs.get("workflow_model")
            or inputs.get("model")
            or inputs.get("workflow_name")
            or "custom-comfyui-workflow"
        )

    @staticmethod
    def _workflow_provenance(
        inputs: dict[str, Any],
        custom_workflow: bool,
        output_node: str,
        operation: str,
        workflow: dict[str, Any],
        model_family: str,
    ) -> dict[str, Any]:
        partner_nodes = {
            "gemini_omni_flash": "GeminiVideoOmni",
            "seedance_2.5": "ByteDance2TextToVideoNode",
            "minimax_h3_api": "MinimaxHailuo03TextToVideoNode",
        }
        if not custom_workflow and model_family in partner_nodes:
            return {
                "source": "comfyui_partner_node",
                "node_class": partner_nodes[model_family],
                "hosted": True,
                "network_required": True,
                "billing": "ComfyUI Partner Node credits",
                "workflow_hash_sha256": workflow_hash(workflow),
                "output_node": output_node,
            }
        if not custom_workflow and model_family == "minimax_h3_hyperflow_local":
            return {
                "source": "bundled",
                "workflow": _HYPERFLOW_WORKFLOWS.get(operation),
                "workflow_hash_sha256": workflow_hash(workflow),
                "model_stack": BUNDLED_MODEL_STACKS["minimax-h3-hyperflow-local"],
                "model": inputs.get("checkpoint_name"),
                "output_node": output_node,
            }
        if not custom_workflow:
            workflow_key = (
                "wan22-i2v-4step"
                if operation == "image_to_video"
                else "wan22-t2v-4step"
            )
            return {
                "source": "bundled",
                "workflow": (
                    "wan22-i2v-4step.json"
                    if operation == "image_to_video"
                    else "wan22-t2v-4step.json"
                ),
                "workflow_hash_sha256": workflow_hash(workflow),
                "model_stack": model_stack(workflow_key, inputs),
                "output_node": output_node,
            }
        local_h3_stack = {
            "minimax_h3_local": "minimax-h3-local",
            "minimax_h3_hyperflow_local": "minimax-h3-hyperflow-local",
        }.get(model_family)
        local_h3 = local_h3_stack is not None
        return {
            "source": "user_supplied",
            **custom_input_provenance(inputs),
            "workflow_name": inputs.get("workflow_name"),
            "workflow_path": inputs.get("workflow_path"),
            "model": inputs.get("workflow_model") or inputs.get("model"),
            "workflow_hash_sha256": workflow_hash(workflow),
            "model_stack": (
                BUNDLED_MODEL_STACKS[local_h3_stack]
                if local_h3_stack and not inputs.get("workflow_model_stack")
                else model_stack(None, inputs)
            ),
            "model_stack_source": (
                "caller_supplied"
                if inputs.get("workflow_model_stack")
                else "official_minimax_h3_stack"
                if local_h3
                else "unknown_custom_workflow"
            ),
            "output_node": output_node,
        }

    @staticmethod
    def _build_partner_t2v(
        inputs: dict[str, Any], seed: int, output_path: Path, model_family: str
    ) -> tuple[dict[str, Any], str]:
        duration = int(inputs.get("duration", 5))
        ratio = inputs.get("aspect_ratio", "16:9")
        resolution = inputs.get("resolution", "720p")
        if model_family == "gemini_omni_flash":
            node_class = "GeminiVideoOmni"
            model = {
                "model": "Omni Flash",
                "prompt": (
                    f"{inputs['prompt']}\nGenerate a {duration}-second {ratio} video."
                ),
                "temperature": 1.0,
                "top_p": 0.95,
            }
        elif model_family == "seedance_2.5":
            node_class = "ByteDance2TextToVideoNode"
            model = {
                "model": "Seedance 2.5",
                "prompt": inputs["prompt"],
                "resolution": resolution if resolution in {"480p", "720p"} else "720p",
                "ratio": ratio,
                "duration": duration,
                "generate_audio": bool(inputs.get("generate_audio", True)),
            }
        else:
            node_class = "MinimaxHailuo03TextToVideoNode"
            model = {
                "model": "MiniMax H3",
                "prompt": inputs["prompt"],
                "resolution": "768P"
                if resolution not in {"768P", "2K"}
                else resolution,
                "ratio": ratio,
                "duration": duration,
            }
        workflow = {
            "1": {
                "class_type": node_class,
                "inputs": {"model": model, "seed": seed, "watermark": False},
            },
            "2": {
                "class_type": "SaveVideo",
                "inputs": {
                    "video": ["1", 0],
                    "filename_prefix": f"video/{output_path.stem}",
                    "format": "auto",
                    "codec": {"codec": "auto"},
                },
            },
        }
        if model_family == "gemini_omni_flash":
            workflow["1"]["inputs"].pop("watermark", None)
        return workflow, "2"
