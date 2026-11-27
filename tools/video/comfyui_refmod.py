"""Extract approved project references into local MiniMax H3 RefMods."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from lib.narrative_assets import (
    CHARACTER_REFERENCE_ROLES,
    NarrativeAssets,
    character_reference_mode,
)
from tools._comfyui.client import ComfyUIClient, ComfyUIError
from tools._comfyui.h3_contracts import (
    REFMOD_EXTRACTION_NODE_INPUT_REQUIREMENTS,
    REFMOD_MULTI_IMAGE_EXTRACTION_NODE_INPUT_REQUIREMENTS,
    REFMOD_VIDEO_NODE_INPUT_REQUIREMENTS,
)
from tools._comfyui.metadata import COMFYUI_SETUP_OFFER, workflow_hash
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


_WORKFLOW = Path(__file__).resolve().parent.parent / "_comfyui" / "workflows" / "refmod_extract_api.json"
_REFMOD_NODE_ID = "4"
_REFMOD_NODE_CLASS = "MiniMaxH3RefModExtract"
_REFMOD_MODE = "Compressed Reference"
_REFMOD_LEGACY_WORKFLOW_VERSION = "refmod-extract-v1"
_REFMOD_MULTI_IMAGE_WORKFLOW_VERSION = "refmod-extract-v2"
_REFMOD_CONCEPT_TYPES = {"identity", "clothing", "background", "generic", "style"}
_APPROVED_ASSET_KINDS = {"character", "location", "prop"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _refmod_extension_version(workspace: Path) -> str:
    pyproject = workspace / "custom_nodes" / "ComfyUI-MiniMaxH3Mod" / "pyproject.toml"
    if not pyproject.is_file():
        return "unversioned"
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return "unversioned"
    match = re.search(r"(?m)^\s*version\s*=\s*['\"]([^'\"]+)['\"]", content)
    return match.group(1).strip() if match and match.group(1).strip() else "unversioned"


def _safe_segment(value: str, label: str, *, strict: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"RefMod {label} cannot be empty")
    original = value.strip()
    if strict:
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", original)
                or original in {".", ".."}):
            raise ValueError(f"RefMod {label} must be a single safe path component")
        return original
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", original).strip(".-_")
    if not slug or slug in {".", ".."}:
        slug = "state" if label == "state" else "asset"
    suffix = hashlib.sha256(original.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:48]}-{suffix}"


def derive_refmod_paths(
    *,
    project_dir: str | Path,
    comfyui_workspace: str | Path,
    project_id: str,
    asset_id: str,
    entity_id: str,
    state: str,
    source_sha256: str,
    concept_type: str,
    video_vae_name: str,
    refmod_extension_version: str = "unversioned",
    workflow_version: str = _REFMOD_LEGACY_WORKFLOW_VERSION,
) -> dict[str, Any]:
    """Build collision-resistant project and ComfyUI paths for one RefMod."""
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("RefMod source_sha256 must be a lowercase SHA-256 digest")
    if concept_type not in _REFMOD_CONCEPT_TYPES:
        raise ValueError(f"Unsupported RefMod concept type: {concept_type}")
    if not isinstance(video_vae_name, str) or not video_vae_name.strip():
        raise ValueError("RefMod extraction needs the approved H3 video VAE name")
    if not isinstance(refmod_extension_version, str) or not refmod_extension_version.strip():
        raise ValueError("RefMod extraction needs an extension version or the marker 'unversioned'")

    project_segment = _safe_segment(project_id, "project_id", strict=True)
    asset_segment = _safe_segment(asset_id, "asset_id")
    entity_segment = _safe_segment(entity_id, "entity_id", strict=True)
    state_segment = _safe_segment(state or "default", "state")
    settings = json.dumps(
        {
            "concept_type": concept_type,
            "entity_id": entity_segment,
            "video_vae_name": video_vae_name,
            "refmod_extension_version": refmod_extension_version,
            "mode": _REFMOD_MODE,
            "workflow": workflow_version,
        },
        sort_keys=True,
    )
    settings_sha256 = hashlib.sha256(settings.encode("utf-8")).hexdigest()[:10]
    filename = f"{asset_segment}-{state_segment}-{source_sha256[:12]}-{settings_sha256}.safetensors"
    loader_name = f"openmontage/{project_segment}/{filename[:-len('.safetensors')]}"

    project_root = Path(project_dir).resolve()
    workspace_root = Path(comfyui_workspace).resolve()
    project_path = (project_root / "assets" / "refmods" / filename).resolve()
    model_library_root = (workspace_root / "models" / "refmods").resolve()
    model_library_path = (model_library_root / f"{loader_name}.safetensors").resolve()
    if not project_path.is_relative_to(project_root):
        raise ValueError("RefMod project path would leave the project directory")
    if not model_library_path.is_relative_to(model_library_root):
        raise ValueError("RefMod loader path would leave models/refmods")
    return {
        "project_path": project_path,
        "loader_name": loader_name,
        "project_id": project_segment,
        "entity_id": entity_segment,
        "model_library_path": model_library_path,
        "model_library_root": model_library_root,
        "source_sha256": source_sha256,
        "refmod_extension_version": refmod_extension_version,
    }


def _is_local_or_shared_workspace(server_url: str, workspace: Path) -> bool:
    try:
        parsed = urlsplit(server_url)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            return False
        return workspace.is_dir()
    except (TypeError, ValueError):
        return False


def _saved_mod_path(entry: dict[str, Any], workspace: Path) -> Path:
    outputs = entry.get("outputs", {})
    node_output = outputs.get(_REFMOD_NODE_ID, {}) if isinstance(outputs, dict) else {}
    text = node_output.get("text") if isinstance(node_output, dict) else None
    if text is None and isinstance(node_output, dict):
        text = (node_output.get("ui") or {}).get("text")
    if isinstance(text, list):
        text = next((item for item in text if isinstance(item, str)), None)
    if not isinstance(text, str):
        raise ValueError("RefMod extractor returned no saved-path details")
    try:
        details = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("RefMod extractor returned malformed saved-path details") from exc
    saved_paths = details.get("saved_paths") if isinstance(details, dict) else None
    if not isinstance(saved_paths, list) or not saved_paths or not isinstance(saved_paths[0], str):
        raise ValueError("RefMod extractor did not save a .safetensors file")
    path = Path(saved_paths[0])
    return (path if path.is_absolute() else workspace / path).resolve()


def _read_refmod_metadata(path: Path) -> dict[str, Any]:
    """Read the RefMod JSON metadata from a safetensors header only."""
    with path.open("rb") as source:
        header_length_bytes = source.read(8)
        if len(header_length_bytes) != 8:
            raise ValueError("RefMod output has a truncated safetensors header")
        header_length = int.from_bytes(header_length_bytes, "little")
        if header_length <= 0 or header_length > path.stat().st_size - 8:
            raise ValueError("RefMod output has an invalid safetensors header length")
        try:
            header = json.loads(source.read(header_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("RefMod output has malformed safetensors metadata") from exc
    container_metadata = header.get("__metadata__") if isinstance(header, dict) else None
    encoded_metadata = (
        container_metadata.get("refmod_meta")
        if isinstance(container_metadata, dict)
        else None
    )
    if not isinstance(encoded_metadata, str):
        raise ValueError("RefMod output is missing the refmod_meta header")
    try:
        metadata = json.loads(encoded_metadata)
    except json.JSONDecodeError as exc:
        raise ValueError("RefMod output has malformed refmod_meta JSON") from exc
    if not isinstance(metadata, dict):
        raise ValueError("RefMod output metadata must be a JSON object")
    return metadata


def _verify_refmod_image_members(path: Path, expected_count: int) -> None:
    metadata = _read_refmod_metadata(path)
    if metadata.get("kind") == "bundle":
        if metadata.get("_format_version") != 5:
            raise ValueError("RefMod output uses an unsupported bundle format")
        members = metadata.get("members")
    else:
        members = [metadata]
    if not isinstance(members, list) or len(members) != expected_count:
        actual_count = len(members) if isinstance(members, list) else 0
        raise ValueError(
            f"RefMod output contains {actual_count} image members; expected {expected_count}"
        )
    if any(not isinstance(member, dict) or member.get("kind") != "image" for member in members):
        raise ValueError("RefMod output contains a non-image member")
    for index, member in enumerate(members, start=1):
        tags = member.get("tags")
        expected_tag = f"separate ref {index}/{expected_count}"
        if not isinstance(tags, list) or expected_tag not in tags:
            raise ValueError(
                f"RefMod output member {index} is not tagged {expected_tag!r}"
            )


def _multi_image_contract_errors(client: ComfyUIClient) -> list[str]:
    """Check the live autogrow type/capacity and required RefMod enum values."""
    node_info = client.get_node_info(_REFMOD_NODE_CLASS)
    inputs = node_info.get("input", {})
    if not isinstance(inputs, dict):
        return ["MiniMaxH3RefModExtract has no valid input schema"]
    input_fields = {
        **(inputs.get("required", {}) if isinstance(inputs.get("required"), dict) else {}),
        **(inputs.get("optional", {}) if isinstance(inputs.get("optional"), dict) else {}),
    }
    errors = []
    refs_image = input_fields.get("refs_image")
    if (
        not isinstance(refs_image, list)
        or len(refs_image) < 2
        or refs_image[0] != "COMFY_AUTOGROW_V3"
    ):
        errors.append("refs_image is not a ComfyUI autogrow input")
    else:
        detail = refs_image[1] if isinstance(refs_image[1], dict) else {}
        template = detail.get("template", {})
        template = template if isinstance(template, dict) else {}
        template_input = template.get("input", {})
        template_input = template_input if isinstance(template_input, dict) else {}
        required_template_inputs = template_input.get("required", {})
        required_template_inputs = (
            required_template_inputs
            if isinstance(required_template_inputs, dict)
            else {}
        )
        image_template = required_template_inputs.get("ref_image")
        if template.get("prefix") != "ref_image_":
            errors.append("refs_image does not use the ref_image_ socket prefix")
        if (
            not isinstance(template.get("max"), int)
            or template["max"] < len(CHARACTER_REFERENCE_ROLES)
        ):
            errors.append("refs_image does not expose five image slots")
        if (
            not isinstance(image_template, list)
            or not image_template
            or image_template[0] != "IMAGE"
        ):
            errors.append("refs_image slots are not IMAGE inputs")

    for field_name, required_value in (
        ("image_refs", "separate"),
        ("budget_policy", "error"),
    ):
        field = input_fields.get(field_name)
        options = (
            field[1].get("options", [])
            if isinstance(field, list)
            and len(field) > 1
            and isinstance(field[1], dict)
            else []
        )
        if (
            not isinstance(field, list)
            or not field
            or field[0] != "COMBO"
            or not isinstance(options, list)
            or required_value not in options
        ):
            errors.append(f"{field_name} does not support {required_value!r}")
    return errors


def _source_set_is_current(source_files: list[dict[str, Any]]) -> bool:
    try:
        return all(
            _sha256_file(item["full_path"]) == item["source_sha256"]
            for item in source_files
        )
    except OSError:
        return False


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


class ComfyUIRefMod(BaseTool):
    name = "comfyui_refmod"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "asset_conditioning"
    provider = "comfyui"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL_GPU
    setup_offer = COMFYUI_SETUP_OFFER
    install_instructions = (
        "Requires a local or shared ComfyUI workspace with the MiniMax H3 RefMod nodes, "
        "an H3 video VAE, and a reachable server_url from the live ComfyUI target."
    )
    capabilities = ["project_scoped_refmod_extraction"]
    best_for = ["Encoding approved reusable H3 character, clothing, location, and prop references"]
    not_good_for = ["Hosted H3 routes, one-off motion references, and FL2VA keyframe shots"]
    agent_skills = ["minimax-h3", "comfyui"]
    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=6000, vram_mb=6000, disk_mb=64, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = [
        "project_id", "asset_id", "reference_path", "reference_images",
        "concept_type", "video_vae_name", "server_url"
    ]
    side_effects = [
        "writes a project RefMod asset",
        "writes a project-scoped loader copy under the ComfyUI models/refmods folder",
        "updates narrative asset provenance",
    ]
    user_visible_verification = [
        "Inspect the approved source and confirm the returned project and loader paths map to the same RefMod hash"
    ]
    input_schema = {
        "type": "object",
        "required": [
            "project_id", "project_dir", "comfyui_workspace", "server_url", "asset_id",
            "video_vae_name", "concept_type",
        ],
        "properties": {
            "project_id": {"type": "string", "minLength": 1},
            "project_dir": {"type": "string", "minLength": 1},
            "comfyui_workspace": {"type": "string", "minLength": 1},
            "server_url": {"type": "string", "minLength": 1},
            "asset_id": {"type": "string", "minLength": 1},
            "reference_path": {"type": "string", "minLength": 1},
            "reference_images": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "required": ["role", "path"],
                    "properties": {
                        "role": {"type": "string", "enum": list(CHARACTER_REFERENCE_ROLES)},
                        "path": {"type": "string", "minLength": 1},
                    },
                    "additionalProperties": False,
                },
            },
            "video_vae_name": {"type": "string", "minLength": 1},
            "concept_type": {"type": "string", "enum": sorted(_REFMOD_CONCEPT_TYPES)},
            "timeout_seconds": {"type": "integer", "minimum": 1, "default": 3600},
        },
        "oneOf": [
            {"required": ["reference_path"], "not": {"required": ["reference_images"]}},
            {"required": ["reference_images"], "not": {"required": ["reference_path"]}},
        ],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self._client = ComfyUIClient(capability="video")

    def get_status(self) -> ToolStatus:
        if not self._client.is_available():
            return ToolStatus.UNAVAILABLE
        if not self._client.has_node(_REFMOD_NODE_CLASS):
            return ToolStatus.DEGRADED
        return ToolStatus.AVAILABLE

    @staticmethod
    def _cache_matches(catalog: NarrativeAssets, asset_id: str, paths: dict[str, Any], concept_type: str, video_vae_name: str) -> bool:
        record = catalog.data.get("refmod_assets", {}).get(asset_id)
        if not isinstance(record, dict):
            return False
        asset = catalog.data.get("assets", {}).get(asset_id)
        if not isinstance(asset, dict):
            return False
        if (record.get("project_path") != str(paths["project_path"].relative_to(catalog.root))
                or record.get("loader_name") != paths["loader_name"]
                or record.get("source_sha256") != paths["source_sha256"]
                or record.get("concept_type") != concept_type
                or record.get("entity_id") != str(asset.get("entity_id") or asset_id)
                or record.get("state") != str(asset.get("state") or "default")
                or record.get("project_id") not in (None, paths["project_id"])):
            return False
        if not catalog._refmod_is_current(asset_id, record):
            return False
        model_stack = record.get("extractor", {}).get("model_stack", [])
        extension_version = ComfyUIRefMod._refmod_extension_version_from_record(record)
        if extension_version != paths["refmod_extension_version"]:
            return False
        if not any(item.get("role") == "video_vae" and item.get("name") == video_vae_name
                   for item in model_stack if isinstance(item, dict)):
            return False
        canonical, loader_copy = paths["project_path"], paths["model_library_path"]
        if not canonical.is_file():
            return False
        recorded_hash = record.get("refmod_sha256")
        if not recorded_hash or _sha256_file(canonical) != recorded_hash:
            return False
        if not loader_copy.is_file() or _sha256_file(loader_copy) != recorded_hash:
            loader_copy.parent.mkdir(parents=True, exist_ok=True)
            _copy_file_atomic(canonical, loader_copy)
        return _sha256_file(loader_copy) == recorded_hash

    @staticmethod
    def _refmod_extension_version_from_record(record: dict[str, Any]) -> str:
        model_stack = record.get("extractor", {}).get("model_stack", [])
        for item in model_stack:
            if isinstance(item, dict) and item.get("role") == "refmod_extension":
                return str(item.get("version") or "unversioned")
        return "unversioned"

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            project_root = Path(inputs["project_dir"]).resolve()
            workspace = Path(inputs["comfyui_workspace"]).resolve()
            server_url = str(inputs["server_url"]).strip()
            if not _is_local_or_shared_workspace(server_url, workspace):
                return ToolResult(
                    success=False,
                    error="ComfyUI workspace must be local or shared and accessible for RefMod extraction",
                )
            if not (project_root / "artifacts" / "narrative_assets.json").is_file():
                return ToolResult(success=False, error="RefMod extraction requires a project narrative asset catalog")

            catalog = NarrativeAssets(project_root)
            asset_id = inputs["asset_id"]
            asset = catalog.data.get("assets", {}).get(asset_id)
            if not isinstance(asset, dict) or asset.get("kind") not in _APPROVED_ASSET_KINDS:
                return ToolResult(success=False, error=f"Unknown RefMod source asset: {asset_id}")
            reference_mode = character_reference_mode(asset)
            if reference_mode == "invalid":
                return ToolResult(
                    success=False,
                    error="The character reference set has an unsupported shape",
                )
            has_legacy_reference = inputs.get("reference_path") is not None
            has_reference_images = inputs.get("reference_images") is not None
            if has_legacy_reference == has_reference_images:
                return ToolResult(
                    success=False,
                    error="RefMod extraction needs exactly one of reference_path or reference_images",
                )

            source_reference_records = None
            source_files: list[dict[str, Any]] = []
            if has_reference_images:
                if asset.get("kind") != "character" or reference_mode != "multi_view":
                    return ToolResult(
                        success=False,
                        error="Five-view reference_images require an approved five-view character asset",
                    )
                approved_references = asset.get("reference_images")
                requested_references = inputs["reference_images"]
                if not isinstance(approved_references, list) or not isinstance(requested_references, list):
                    return ToolResult(
                        success=False,
                        error="RefMod extraction requires the approved five-view character reference set",
                    )
                if len(requested_references) != len(CHARACTER_REFERENCE_ROLES):
                    return ToolResult(
                        success=False,
                        error="A character RefMod requires exactly five approved image references",
                    )
                if len(approved_references) != len(CHARACTER_REFERENCE_ROLES):
                    return ToolResult(
                        success=False,
                        error="The approved character asset does not contain exactly five reference images",
                    )
                source_reference_records = []
                for index, (requested, approved, expected_role) in enumerate(
                    zip(requested_references, approved_references, CHARACTER_REFERENCE_ROLES),
                    start=1,
                ):
                    if (
                        not isinstance(requested, dict)
                        or set(requested) != {"role", "path"}
                        or not isinstance(approved, dict)
                    ):
                        return ToolResult(
                            success=False,
                            error=f"Character reference {index} is not a valid role/path record",
                        )
                    if requested.get("role") != expected_role or approved.get("role") != expected_role:
                        return ToolResult(
                            success=False,
                            error=f"Character reference {index} must use role {expected_role}",
                        )
                    requested_path = requested.get("path")
                    approved_path = approved.get("path")
                    if not isinstance(requested_path, str) or not isinstance(approved_path, str):
                        return ToolResult(
                            success=False,
                            error=f"Character reference {index} is missing its approved path",
                        )
                    normalized_requested = catalog._media(requested_path)
                    normalized_approved = catalog._media(approved_path)
                    if normalized_requested != normalized_approved:
                        return ToolResult(
                            success=False,
                            error=f"RefMod source path does not match approved character view {expected_role}",
                        )
                    full_path = (project_root / normalized_requested).resolve()
                    source_hash = _sha256_file(full_path)
                    source_reference_records.append(
                        {
                            "role": expected_role,
                            "path": normalized_requested,
                            "source_sha256": source_hash,
                        }
                    )
                    source_files.append(
                        {"role": expected_role, "path": normalized_requested, "full_path": full_path, "source_sha256": source_hash}
                    )
                if len({item["path"] for item in source_files}) != len(CHARACTER_REFERENCE_ROLES):
                    return ToolResult(
                        success=False,
                        error="Character RefMod references must use five distinct approved files",
                    )
                if source_reference_records[0]["path"] != catalog._media(asset["path"]):
                    return ToolResult(
                        success=False,
                        error="The first RefMod source must be the approved front portrait",
                    )
                source_sha256 = catalog.source_reference_digest(source_reference_records)
                workflow_version = _REFMOD_MULTI_IMAGE_WORKFLOW_VERSION
            else:
                if reference_mode == "multi_view":
                    return ToolResult(
                        success=False,
                        error="This character has an approved five-view set; pass all five reference_images",
                    )
                approved_path = catalog._media(asset["path"])
                requested_path = catalog._media(inputs["reference_path"])
                if requested_path != approved_path:
                    return ToolResult(
                        success=False,
                        error=f"RefMod source path does not match approved asset {asset_id}",
                    )
                source = (project_root / approved_path).resolve()
                source_sha256 = _sha256_file(source)
                source_files.append(
                    {"role": None, "path": approved_path, "full_path": source, "source_sha256": source_sha256}
                )
                workflow_version = _REFMOD_LEGACY_WORKFLOW_VERSION

            extension_version = _refmod_extension_version(workspace)
            paths = derive_refmod_paths(
                project_dir=project_root,
                comfyui_workspace=workspace,
                project_id=inputs["project_id"],
                asset_id=asset_id,
                entity_id=str(asset.get("entity_id") or asset_id),
                state=str(asset.get("state") or "default"),
                source_sha256=source_sha256,
                concept_type=inputs["concept_type"],
                video_vae_name=inputs["video_vae_name"],
                refmod_extension_version=extension_version,
                workflow_version=workflow_version,
            )

            client = ComfyUIClient(server_url=server_url, capability="video")
            if not client.is_available():
                return ToolResult(success=False, error=client.unavailable_reason())
            apply_nodes = (
                "MiniMaxH3RefModsLoader",
                "MiniMaxH3RefModTextEncode",
                "MiniMaxH3ReferenceToVideo",
                "BasicGuider",
            )
            missing_apply_nodes = [
                node for node in apply_nodes if not client.has_node(node)
            ]
            if missing_apply_nodes:
                return ToolResult(
                    success=False,
                    error=(
                        "RefMod application is blocked on the selected ComfyUI server; "
                        "missing nodes: " + ", ".join(missing_apply_nodes)
                    ),
                )
            missing_apply_inputs = []
            for node, required_inputs in REFMOD_VIDEO_NODE_INPUT_REQUIREMENTS.items():
                missing_inputs = client.check_node_inputs(node, required_inputs)
                if missing_inputs:
                    missing_apply_inputs.append(
                        f"{node} ({', '.join(missing_inputs)})"
                    )
            if missing_apply_inputs:
                return ToolResult(
                    success=False,
                    error=(
                        "RefMod application is blocked; the selected ComfyUI server "
                        "has incompatible node inputs: "
                        + ", ".join(missing_apply_inputs)
                    ),
                )
            _, missing_models = client.check_models([inputs["video_vae_name"]])
            if missing_models:
                return ToolResult(
                    success=False,
                    error="RefMod extraction is blocked; missing H3 video VAE: "
                    + ", ".join(missing_models),
                )

            cache_match = self._cache_matches(
                catalog, asset_id, paths, inputs["concept_type"], inputs["video_vae_name"]
            )
            if cache_match:
                record = catalog.data["refmod_assets"][asset_id]
                if record.get("project_id") != inputs["project_id"]:
                    catalog.register_refmod_asset(
                        asset_id,
                        project_id=inputs["project_id"],
                        project_path=record["project_path"],
                        loader_name=record["loader_name"],
                        concept_type=record["concept_type"],
                        source_sha256=source_sha256,
                        extractor=record["extractor"],
                        source_references=record.get("source_references"),
                    )
                    record = catalog.data["refmod_assets"][asset_id]
                data = {**record, "asset_id": asset_id, "from_cache": True}
                return ToolResult(
                    success=True,
                    data=data,
                    artifacts=[str(paths["project_path"])],
                    model="MiniMax H3 RefMod",
                    from_cache=True,
                )
            if paths["model_library_path"].exists() or paths["project_path"].exists():
                return ToolResult(
                    success=False,
                    error=(
                        "RefMod output path collision: an existing Mod is not backed by a matching "
                        "project manifest entry; refusing to overwrite it"
                    ),
                )

            required_nodes = ("LoadImage", "VAELoader", _REFMOD_NODE_CLASS)
            missing_nodes = [node for node in required_nodes if not client.has_node(node)]
            if missing_nodes:
                return ToolResult(success=False, error="RefMod extraction is blocked; missing ComfyUI nodes: " + ", ".join(missing_nodes))

            missing_extraction_inputs = []
            for node, required_inputs in REFMOD_EXTRACTION_NODE_INPUT_REQUIREMENTS.items():
                missing_inputs = client.check_node_inputs(node, required_inputs)
                if missing_inputs:
                    missing_extraction_inputs.append(
                        f"{node} ({', '.join(missing_inputs)})"
                    )
            if missing_extraction_inputs:
                return ToolResult(
                    success=False,
                    error=(
                        "RefMod extraction is blocked; the selected ComfyUI server "
                        "has incompatible node inputs: "
                        + ", ".join(missing_extraction_inputs)
                    ),
                )
            if has_reference_images:
                missing_multi_image_inputs = []
                for node, required_inputs in REFMOD_MULTI_IMAGE_EXTRACTION_NODE_INPUT_REQUIREMENTS.items():
                    missing_inputs = client.check_node_inputs(node, required_inputs)
                    if missing_inputs:
                        missing_multi_image_inputs.append(
                            f"{node} ({', '.join(missing_inputs)})"
                        )
                if missing_multi_image_inputs:
                    return ToolResult(
                        success=False,
                        error=(
                            "Five-view RefMod extraction is blocked; the selected ComfyUI server "
                            "is missing the multi-image input group: "
                            + ", ".join(missing_multi_image_inputs)
                        ),
                    )
                multi_image_contract_errors = _multi_image_contract_errors(client)
                if multi_image_contract_errors:
                    return ToolResult(
                        success=False,
                        error=(
                            "Five-view RefMod extraction is blocked; the selected ComfyUI server "
                            "does not meet the multi-image contract: "
                            + "; ".join(multi_image_contract_errors)
                        ),
                    )

            paths["model_library_root"].mkdir(parents=True, exist_ok=True)
            workflow = json.loads(_WORKFLOW.read_text(encoding="utf-8"))
            if has_reference_images:
                workflow[_REFMOD_NODE_ID]["inputs"]["budget_policy"] = "error"
            else:
                workflow[_REFMOD_NODE_ID]["inputs"]["budget_policy"] = "truncate"
                for slot in range(1, len(CHARACTER_REFERENCE_ROLES)):
                    workflow[_REFMOD_NODE_ID]["inputs"].pop(f"refs_image.ref_image_{slot}", None)
                for node_id in ("5", "6", "7", "8"):
                    workflow.pop(node_id, None)
            workflow_hash_sha256 = workflow_hash(workflow)
            basename = paths["loader_name"].rsplit("/", 1)[1]
            subfolder = paths["loader_name"].rsplit("/", 1)[0]
            bindings = {
                "video_vae_name": [{"node": "3", "input": "vae_name"}],
                "refmod_name": [{"node": _REFMOD_NODE_ID, "input": "name"}],
                "refmod_subfolder": [{"node": _REFMOD_NODE_ID, "input": "subfolder"}],
                "concept_type": [{"node": _REFMOD_NODE_ID, "input": "concept_type"}],
                "description": [{"node": _REFMOD_NODE_ID, "input": "description"}],
            }
            with tempfile.TemporaryDirectory(prefix="openmontage-refmod-") as temp_dir:
                staged_source_paths: list[tuple[Path, str]] = []
                binding_values: dict[str, Any] = {
                    "video_vae_name": inputs["video_vae_name"],
                    "refmod_name": basename,
                    "refmod_subfolder": subfolder,
                    "concept_type": inputs["concept_type"],
                    "description": str(asset.get("description", "")),
                }
                if has_reference_images:
                    role_to_node = {
                        "portrait_front": "1",
                        "portrait_side": "5",
                        "full_body_front_headless": "6",
                        "full_body_side_headless": "7",
                        "full_body_back_headed": "8",
                    }
                    role_paths = {}
                    for source_item in source_files:
                        role = source_item["role"]
                        snapshot = Path(temp_dir) / f"{role}{source_item['full_path'].suffix}"
                        shutil.copyfile(source_item["full_path"], snapshot)
                        if _sha256_file(snapshot) != source_item["source_sha256"]:
                            return ToolResult(
                                success=False,
                                error=f"Approved character view {role} changed while staging; review and retry extraction",
                            )
                        staged_source_paths.append((snapshot, source_item["source_sha256"]))
                        role_paths[role] = str(snapshot)
                        bindings[f"reference_images.{role}"] = [
                            {"node": role_to_node[role], "input": "image"}
                        ]
                    binding_values["reference_images"] = role_paths
                else:
                    snapshot = Path(temp_dir) / f"portrait-front{source_files[0]['full_path'].suffix}"
                    shutil.copyfile(source_files[0]["full_path"], snapshot)
                    if _sha256_file(snapshot) != source_files[0]["source_sha256"]:
                        return ToolResult(
                            success=False,
                            error="Approved source changed while staging; review and retry extraction",
                        )
                    staged_source_paths.append((snapshot, source_files[0]["source_sha256"]))
                    bindings["reference_image_path"] = [{"node": "1", "input": "image"}]
                    binding_values["reference_image_path"] = str(snapshot)
                workflow = client.bind_workflow(workflow, bindings, binding_values)
                if any(
                    _sha256_file(snapshot) != expected_hash
                    for snapshot, expected_hash in staged_source_paths
                ):
                    return ToolResult(
                        success=False,
                        error="A staged RefMod image changed during upload; retry extraction",
                    )
                if not _source_set_is_current(source_files):
                    return ToolResult(
                        success=False,
                        error="An approved source changed before RefMod submission; review and retry extraction",
                    )
            prompt_id = client.submit(workflow)
            history = client.poll(
                prompt_id,
                timeout=int(inputs.get("timeout_seconds", 3600)),
                interval=5,
            )
            saved_path = _saved_mod_path(history, workspace)
            if not saved_path.is_file():
                return ToolResult(success=False, error="RefMod extractor reported a file that does not exist")
            if not saved_path.is_relative_to(paths["model_library_root"]):
                return ToolResult(success=False, error="RefMod extractor wrote outside the selected models/refmods workspace")
            if saved_path != paths["model_library_path"]:
                return ToolResult(success=False, error="RefMod extractor saved an unexpected loader path")

            if not _source_set_is_current(source_files):
                saved_path.unlink(missing_ok=True)
                return ToolResult(
                    success=False,
                    error="An approved source changed during extraction; no RefMod was registered",
                )

            if has_reference_images:
                try:
                    _verify_refmod_image_members(saved_path, len(source_files))
                except ValueError:
                    saved_path.unlink(missing_ok=True)
                    raise

            mod_sha256 = _sha256_file(saved_path)
            project_path = paths["project_path"]
            project_path.parent.mkdir(parents=True, exist_ok=True)
            if project_path.exists() and _sha256_file(project_path) != mod_sha256:
                raise ValueError("RefMod project output already exists with different contents; refusing overwrite")
            if not project_path.exists():
                _copy_file_atomic(saved_path, project_path)
            extractor = {
                "tool": self.name,
                "node": _REFMOD_NODE_CLASS,
                "workflow_hash_sha256": workflow_hash_sha256,
                "model_stack": [
                    {"role": "refmod_extension", "name": "ComfyUI-MiniMaxH3Mod", "version": extension_version},
                    {"role": "video_vae", "name": inputs["video_vae_name"]},
                ],
            }
            try:
                catalog.register_refmod_asset(
                    asset_id,
                    project_id=inputs["project_id"],
                    project_path=str(project_path),
                    loader_name=paths["loader_name"],
                    concept_type=inputs["concept_type"],
                    source_sha256=source_sha256,
                    extractor=extractor,
                    source_references=source_reference_records,
                )
            except Exception:
                project_path.unlink(missing_ok=True)
                saved_path.unlink(missing_ok=True)
                raise
            data = {
                "asset_id": asset_id,
                "project_path": str(project_path.relative_to(project_root)),
                "loader_name": paths["loader_name"],
                "source_sha256": source_sha256,
                "refmod_sha256": mod_sha256,
                "extractor": extractor,
                "prompt_id": prompt_id,
                "from_cache": False,
            }
            if source_reference_records is not None:
                data["source_references"] = source_reference_records
            return ToolResult(
                success=True,
                data=data,
                artifacts=[str(project_path)],
                model="MiniMax H3 RefMod",
            )
        except (ComfyUIError, OSError, TypeError, ValueError, KeyError) as exc:
            prompt_id = getattr(exc, "prompt_id", None)
            return ToolResult(
                success=False,
                error=f"MiniMax H3 RefMod extraction failed: {exc}",
                data={"prompt_id": prompt_id} if prompt_id else {},
            )
