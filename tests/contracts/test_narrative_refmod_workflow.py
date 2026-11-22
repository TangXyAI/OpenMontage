"""Integration contract for the cinematic RefMod-to-H3 asset path."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from lib.narrative_assets import NarrativeAssets
from lib.video_model_selection import build_menu, record_reference_conditioning_selection
from tools._comfyui.client import ComfyUIClient as RealComfyUIClient
from tools.base_tool import ToolResult
from tools.video.comfyui_refmod import ComfyUIRefMod
from tools.video.comfyui_video import ComfyUIVideo


SERVER_URL = "http://127.0.0.1:8290"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
OPTIONS = [
    {
        "option_id": "project_refmod",
        "label": "Project RefMods",
        "score": 1.0,
        "reason": "Reuse approved project assets for local H3 shots.",
    },
    {
        "option_id": "native_ref2va",
        "label": "Native Ref2VA",
        "score": 0.7,
        "reason": "Keep ordinary H3 visual references.",
    },
]


class RecordingComfyUIClient(RealComfyUIClient):
    workspace: Path | None = None
    instances: list["RecordingComfyUIClient"] = []
    missing_nodes: set[str] = set()
    missing_models: set[str] = set()
    submissions = 0

    def __init__(self, server_url=None, capability=None):
        self.server_url = server_url or "http://localhost:8188"
        self.capability = capability
        self.workspace = type(self).workspace
        self.last_timing = {}
        self.workflow = None
        self.submission_count = 0
        self.instances.append(self)

    def is_available(self):
        return True

    def unavailable_reason(self):
        return "fake server unavailable"

    def has_node(self, _node_class):
        return _node_class not in type(self).missing_nodes

    def check_models(self, required):
        missing = [name for name in required if name in type(self).missing_models]
        return [name for name in required if name not in missing], missing

    def check_node_inputs(self, _node_class, _required_inputs):
        return []

    def upload_image(self, local_path, _name):
        return f"remote-{Path(local_path).name}"

    def bind_workflow(self, workflow, bindings, values):
        bound = copy.deepcopy(workflow)
        for parameter, targets in bindings.items():
            if parameter.startswith("reference_images."):
                key = parameter.split(".", 1)[1]
                value = (values.get("reference_images") or {}).get(key)
            else:
                value = values.get(parameter)
            if value is None:
                raise AssertionError(f"test fixture has no binding value for {parameter}")
            if parameter == "reference_image_path" or parameter.startswith(
                "reference_images."
            ):
                value = self.upload_image(value, Path(value).name)
            for target in targets:
                bound[str(target["node"])]["inputs"][target["input"]] = value
        return bound

    def submit(self, workflow):
        self.workflow = copy.deepcopy(workflow)
        self.submission_count += 1
        return f"prompt-{self.submission_count}"

    def poll(self, _prompt_id, *, timeout, interval):
        del timeout, interval
        inputs = self.workflow["4"]["inputs"]
        target = (
            self.workspace
            / "models"
            / "refmods"
            / inputs["subfolder"]
            / f"{inputs['name']}.safetensors"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"generated-refmod:" + inputs["name"].encode("utf-8"))
        details = json.dumps({"saved_paths": [str(target)]})
        return {"outputs": {"4": {"text": [details]}}}

    def generate(self, workflow, output_node, dest, **_kwargs):
        self.workflow = copy.deepcopy(workflow)
        self.output_node = output_node
        type(self).submissions += 1
        return [Path(dest)]


class FakeTool:
    def __init__(self, status="unavailable"):
        self.status = status

    def get_status(self):
        return type("Status", (), {"value": self.status})()

    def get_info(self):
        return {"install_instructions": "start the configured ComfyUI server"}

    def estimate_cost(self, _inputs):
        return 0.0


class FakeRegistry:
    def __init__(self):
        self._tools = {
            "comfyui_video": FakeTool("unavailable"),
            "minimax_video": FakeTool("available"),
        }


def _create_project(project: Path) -> NarrativeAssets:
    sources = {
        "hero-wet": ("character", "Courier in a soaked coat", "wet"),
        "loc-master": ("location", "Empty workshop master", "master_plate"),
    }
    catalog = NarrativeAssets(project)
    for asset_id, (kind, description, state) in sources.items():
        path = project / "assets" / "images" / f"{asset_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"approved:{asset_id}".encode("utf-8"))
        catalog.put_asset(
            asset_id,
            kind,
            description,
            str(path.relative_to(project)),
            state=state,
            entity_id="hero" if asset_id == "hero-wet" else "workshop",
        )
    catalog.register_shot("s01-sh01", "s01")
    catalog.link_assets("s01-sh01", ["hero-wet", "loc-master"])
    return catalog


def _run_pilot(project: Path, workspace: Path, monkeypatch):
    from tools.video import comfyui_refmod as refmod_module
    from tools.video import comfyui_video as video_module
    from lib import video_model_selection as selection_module

    project.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    extension = workspace / "custom_nodes" / "ComfyUI-MiniMaxH3Mod" / "pyproject.toml"
    extension.parent.mkdir(parents=True)
    extension.write_text('[project]\nversion = "0.2.7"\n', encoding="utf-8")
    catalog = _create_project(project)

    decision_path = project / "artifacts" / "decision_log.json"
    decision = record_reference_conditioning_selection(
        decision_path,
        "film-a",
        "assets",
        "project_refmod",
        OPTIONS,
        "Use approved reusable assets for local H3 Ref2VA shots.",
    )
    catalog.record_refmod_usage(
        "project_refmod", route_id="hyperflow_gguf", decision_id=decision["decision_id"]
    )

    extractor = ComfyUIRefMod()
    video_tool = ComfyUIVideo()
    RecordingComfyUIClient.workspace = workspace
    RecordingComfyUIClient.instances.clear()
    RecordingComfyUIClient.missing_nodes = set()
    RecordingComfyUIClient.missing_models = set()
    RecordingComfyUIClient.submissions = 0
    monkeypatch.setattr(refmod_module, "ComfyUIClient", RecordingComfyUIClient)
    monkeypatch.setattr(video_module, "ComfyUIClient", RecordingComfyUIClient)
    monkeypatch.setattr(selection_module, "ComfyUIClient", RecordingComfyUIClient, raising=False)

    menu = build_menu(FakeRegistry(), server_url=SERVER_URL)
    menu_routes = {item["route_id"]: item for item in menu}
    extraction_results = []
    for asset_id, concept_type in (
        ("hero-wet", "identity"),
        ("loc-master", "background"),
    ):
        extraction_results.append(
            extractor.execute(
                {
                    "project_id": "film-a",
                    "project_dir": str(project),
                    "comfyui_workspace": str(workspace),
                    "server_url": SERVER_URL,
                    "asset_id": asset_id,
                    "reference_path": f"assets/images/{asset_id}.png",
                    "video_vae_name": VIDEO_VAE,
                    "concept_type": concept_type,
                }
            )
        )

    refreshed = NarrativeAssets(project)
    shot_refmods = refreshed.refmods_for_shot(
        "s01-sh01", comfyui_workspace=workspace
    )
    result = video_tool.execute(
        {
            "prompt": "<Picture 1> crosses <Picture 2> in falling rain.",
            "model_family": "minimax_h3_hyperflow_local",
            "operation": "reference_to_video",
            "checkpoint_name": "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf",
            "loader": "gguf",
            "refmod_assets": shot_refmods,
            "server_url": SERVER_URL,
            "comfyui_workspace": str(workspace),
            "seed": 12,
            "output_path": str(project / "assets" / "video" / "s01-sh01-take-01.mp4"),
        }
    )
    if result.success:
        take_path = project / "assets" / "video" / "s01-sh01-take-01.mp4"
        take_path.parent.mkdir(parents=True, exist_ok=True)
        take_path.write_bytes(b"synthetic-h3-take")
        refreshed.add_take(
            "s01-sh01",
            "take-01",
            str(take_path.relative_to(project)),
            3.0,
            {
                "source_tool": "comfyui_video",
                "workflow_provenance": result.data["workflow_provenance"],
            },
        )
        refreshed.select_take("s01-sh01", "take-01")
    return {
        "catalog": NarrativeAssets(project),
        "decision": decision,
        "extraction_results": extraction_results,
        "menu_routes": menu_routes,
        "refmods": shot_refmods,
        "result": result,
        "clients": list(RecordingComfyUIClient.instances),
        "workspace": workspace,
        "project": project,
    }


def test_local_h3_pilot_persists_and_applies_project_refmods(tmp_path, monkeypatch):
    pilot = _run_pilot(tmp_path / "projects" / "film-a", tmp_path / "comfy", monkeypatch)

    assert all(result.success for result in pilot["extraction_results"])
    assert pilot["catalog"].asset_manifest()["metadata"]["refmod_assets"]["hero-wet"]["state"] == "wet"
    assert pilot["catalog"].asset_manifest()["metadata"]["refmod_usage"]["decision_id"] == pilot["decision"]["decision_id"]
    assert pilot["result"].success, pilot["result"].error
    assert pilot["result"].data["workflow_provenance"]["refmod_asset_ids"] == [
        "hero-wet",
        "loc-master",
    ]
    assert [item["prompt_label"] for item in pilot["result"].data["workflow_provenance"]["refmod_assets"]] == [
        "<Picture 1>",
        "<Picture 2>",
    ]
    manifest = pilot["catalog"].asset_manifest()
    from schemas.artifacts import validate_artifact

    validate_artifact("asset_manifest", manifest)
    video = next(asset for asset in manifest["assets"] if asset["type"] == "video")
    assert video["refmod_asset_ids"] == ["hero-wet", "loc-master"]
    assert [item["refmod_sha256"] for item in video["refmod_assets"]] == [
        pilot["catalog"].data["refmod_assets"][asset_id]["refmod_sha256"]
        for asset_id in ("hero-wet", "loc-master")
    ]


def test_stale_source_refmod_blocks_before_batch(tmp_path):
    project = tmp_path / "projects" / "film-a"
    catalog = _create_project(project)
    mod_path = project / "assets" / "refmods" / "hero-wet.safetensors"
    mod_path.parent.mkdir(parents=True)
    mod_path.write_bytes(b"cached-mod")
    catalog.register_refmod_asset(
        "hero-wet",
        project_id="film-a",
        project_path="assets/refmods/hero-wet.safetensors",
        loader_name="openmontage/film-a/hero-wet",
        concept_type="identity",
        source_sha256=catalog._sha256(
            project / catalog.data["assets"]["hero-wet"]["path"]
        ),
        extractor={
            "tool": "comfyui_refmod",
            "node": "MiniMaxH3RefModExtract",
            "workflow_hash_sha256": "c" * 64,
        },
    )
    catalog.record_refmod_usage(
        "project_refmod", route_id="hyperflow_gguf", decision_id="d-001"
    )
    (project / "assets" / "images" / "hero-wet.png").write_bytes(b"updated-approved-sheet")
    batch_calls = []

    try:
        refs = catalog.refmods_for_shot("s01-sh01")
    except ValueError as exc:
        result = ToolResult(success=False, error=str(exc))
    else:
        batch_calls.append(refs)
        result = ToolResult(success=True)

    assert not result.success
    assert "stale RefMod" in result.error
    assert batch_calls == []


def _patch_video_client(monkeypatch):
    from tools.video import comfyui_video as video_module

    RecordingComfyUIClient.instances.clear()
    monkeypatch.setattr(video_module, "ComfyUIClient", RecordingComfyUIClient)


def test_fl2va_keyframes_do_not_receive_refmods(tmp_path, monkeypatch):
    _patch_video_client(monkeypatch)
    RecordingComfyUIClient.workspace = tmp_path
    first, last = tmp_path / "first.png", tmp_path / "last.png"
    first.write_bytes(b"first")
    last.write_bytes(b"last")

    result = ComfyUIVideo().execute(
        {
            "prompt": "A runner moves from the doorway to the window.",
            "model_family": "minimax_h3_hyperflow_local",
            "operation": "first_last_frame_to_video",
            "checkpoint_name": "minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf",
            "loader": "gguf",
            "first_frame_image_path": str(first),
            "last_frame_image_path": str(last),
            "server_url": SERVER_URL,
            "seed": 13,
            "output_path": str(tmp_path / "flf.mp4"),
        }
    )

    assert result.success, result.error
    assert result.data["operation"] == "first_last_frame_to_video"
    assert result.data["workflow_provenance"].get("refmod_asset_ids", []) == []


def test_hosted_h3_keeps_native_provider_path(tmp_path, monkeypatch):
    _patch_video_client(monkeypatch)
    RecordingComfyUIClient.workspace = tmp_path

    result = ComfyUIVideo().execute(
        {
            "prompt": "a rain-soaked alley",
            "model_family": "minimax_h3_api",
            "operation": "text_to_video",
            "server_url": SERVER_URL,
            "seed": 14,
            "output_path": str(tmp_path / "hosted.mp4"),
        }
    )

    assert result.success, result.error
    assert result.data["hosted"] is True
    assert result.data["workflow_provenance"]["source"] == "comfyui_partner_node"
    assert result.data["workflow_provenance"].get("refmod_asset_ids", []) == []


def test_local_h3_refmod_blocks_when_selected_checkpoint_is_missing(
    tmp_path, monkeypatch
):
    from tools.video import comfyui_video as video_module

    workspace = tmp_path / "comfy"
    workspace.mkdir()
    RecordingComfyUIClient.workspace = workspace
    RecordingComfyUIClient.instances.clear()
    RecordingComfyUIClient.missing_nodes = set()
    RecordingComfyUIClient.missing_models = {
        "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf"
    }
    RecordingComfyUIClient.submissions = 0
    monkeypatch.setattr(video_module, "ComfyUIClient", RecordingComfyUIClient)
    loader_name = "openmontage/film-a/hero-wet"
    loader_path = workspace / "models" / "refmods" / f"{loader_name}.safetensors"
    loader_path.parent.mkdir(parents=True)
    loader_path.write_bytes(b"approved-mod")
    approved_hash = hashlib.sha256(b"approved-mod").hexdigest()

    result = ComfyUIVideo().execute(
        {
            "prompt": "<Picture 1> crosses the room.",
            "model_family": "minimax_h3_hyperflow_local",
            "operation": "reference_to_video",
            "checkpoint_name": "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf",
            "loader": "gguf",
            "refmod_assets": [{
                "asset_id": "hero-wet",
                "loader_name": loader_name,
                "concept_type": "identity",
                "state": "wet",
                "description": "Courier in a soaked coat",
                "prompt_label": "<Picture 1>",
                "refmod_sha256": approved_hash,
            }],
            "server_url": SERVER_URL,
            "comfyui_workspace": str(workspace),
            "seed": 21,
            "output_path": str(tmp_path / "missing-stack.mp4"),
        }
    )

    assert not result.success
    assert "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf" in result.error
    assert RecordingComfyUIClient.submissions == 0


def test_local_h3_refmod_blocks_tampered_loader_copy_before_submission(
    tmp_path, monkeypatch
):
    from tools.video import comfyui_video as video_module

    workspace = tmp_path / "comfy"
    loader_name = "openmontage/film-a/hero-wet"
    loader_path = workspace / "models" / "refmods" / f"{loader_name}.safetensors"
    loader_path.parent.mkdir(parents=True)
    loader_path.write_bytes(b"tampered-loader-mod")
    expected_hash = hashlib.sha256(b"approved-mod").hexdigest()
    ref = {
        "asset_id": "hero-wet",
        "loader_name": loader_name,
        "concept_type": "identity",
        "state": "wet",
        "description": "Courier in a soaked coat",
        "prompt_label": "<Picture 1>",
        "refmod_sha256": expected_hash,
    }
    RecordingComfyUIClient.workspace = workspace
    RecordingComfyUIClient.instances.clear()
    RecordingComfyUIClient.missing_nodes = set()
    RecordingComfyUIClient.missing_models = set()
    RecordingComfyUIClient.submissions = 0
    monkeypatch.setattr(video_module, "ComfyUIClient", RecordingComfyUIClient)

    result = ComfyUIVideo().execute(
        {
            "prompt": "<Picture 1> walks through rain.",
            "model_family": "minimax_h3_hyperflow_local",
            "operation": "reference_to_video",
            "checkpoint_name": "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf",
            "loader": "gguf",
            "refmod_assets": [ref],
            "server_url": SERVER_URL,
            "comfyui_workspace": str(workspace),
            "seed": 23,
            "output_path": str(tmp_path / "tampered.mp4"),
        }
    )

    assert not result.success
    assert "loader copy hash" in result.error.lower()
    assert RecordingComfyUIClient.submissions == 0


def test_refmod_extraction_and_h3_menu_and_batch_use_the_same_comfy_target(
    tmp_path, monkeypatch
):
    pilot = _run_pilot(tmp_path / "projects" / "film-a", tmp_path / "comfy", monkeypatch)

    assert pilot["result"].success, pilot["result"].error
    assert pilot["menu_routes"]["h3_local"]["available"] is True
    assert pilot["menu_routes"]["hyperflow_int8"]["available"] is True
    assert pilot["menu_routes"]["comfyui_h3_api"]["available"] is False
    assert all(client.server_url == SERVER_URL for client in pilot["clients"])
    assert all(client.capability == "video" for client in pilot["clients"])
    assert all(result.success for result in pilot["extraction_results"])
    assert pilot["clients"][1].workspace == pilot["workspace"]
