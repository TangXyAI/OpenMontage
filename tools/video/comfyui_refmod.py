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

from lib.narrative_assets import NarrativeAssets
from tools._comfyui.client import ComfyUIClient, ComfyUIError
from tools._comfyui.h3_contracts import (
    REFMOD_EXTRACTION_NODE_INPUT_REQUIREMENTS,
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
            "workflow": "refmod-extract-v1",
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
        "project_id", "asset_id", "reference_path", "concept_type", "video_vae_name", "server_url"
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
            "reference_path", "video_vae_name", "concept_type",
        ],
        "properties": {
            "project_id": {"type": "string", "minLength": 1},
            "project_dir": {"type": "string", "minLength": 1},
            "comfyui_workspace": {"type": "string", "minLength": 1},
            "server_url": {"type": "string", "minLength": 1},
            "asset_id": {"type": "string", "minLength": 1},
            "reference_path": {"type": "string", "minLength": 1},
            "video_vae_name": {"type": "string", "minLength": 1},
            "concept_type": {"type": "string", "enum": sorted(_REFMOD_CONCEPT_TYPES)},
            "timeout_seconds": {"type": "integer", "minimum": 1, "default": 3600},
        },
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
            approved_path = catalog._media(asset["path"])
            requested_path = catalog._media(inputs["reference_path"])
            if requested_path != approved_path:
                return ToolResult(success=False, error=f"RefMod source path does not match approved asset {asset_id}")

            source = (project_root / approved_path).resolve()
            source_bytes = source.read_bytes()
            source_sha256 = hashlib.sha256(source_bytes).hexdigest()
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

            paths["model_library_root"].mkdir(parents=True, exist_ok=True)
            workflow = json.loads(_WORKFLOW.read_text(encoding="utf-8"))
            workflow_hash_sha256 = workflow_hash(workflow)
            basename = paths["loader_name"].rsplit("/", 1)[1]
            subfolder = paths["loader_name"].rsplit("/", 1)[0]
            bindings = {
                "reference_image_path": [{"node": "1", "input": "image"}],
                "video_vae_name": [{"node": "3", "input": "vae_name"}],
                "refmod_name": [{"node": _REFMOD_NODE_ID, "input": "name"}],
                "refmod_subfolder": [{"node": _REFMOD_NODE_ID, "input": "subfolder"}],
                "concept_type": [{"node": _REFMOD_NODE_ID, "input": "concept_type"}],
                "description": [{"node": _REFMOD_NODE_ID, "input": "description"}],
            }
            with tempfile.TemporaryDirectory(prefix="openmontage-refmod-") as temp_dir:
                source_snapshot = Path(temp_dir) / source.name
                source_snapshot.write_bytes(source_bytes)
                workflow = client.bind_workflow(workflow, bindings, {
                    "reference_image_path": str(source_snapshot),
                    "video_vae_name": inputs["video_vae_name"],
                    "refmod_name": basename,
                    "refmod_subfolder": subfolder,
                    "concept_type": inputs["concept_type"],
                    "description": str(asset.get("description", "")),
                })
                if _sha256_file(source) != source_sha256:
                    return ToolResult(
                        success=False,
                        error="Approved source changed before RefMod submission; review and retry extraction",
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

            if _sha256_file(source) != source_sha256:
                saved_path.unlink(missing_ok=True)
                return ToolResult(
                    success=False,
                    error="Approved source changed during extraction; no RefMod was registered",
                )

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
