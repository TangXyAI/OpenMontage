import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / "artifacts" / f"{name}.schema.json").read_text(encoding="utf-8"))


def _decision(category: str) -> dict:
    return {
        "version": "1.0",
        "project_id": "p",
        "decisions": [{
            "decision_id": "d-001",
            "stage": "assets",
            "category": category,
            "subject": "Post-enhancement route",
            "options_considered": [{
                "option_id": "seedvr2_upscale", "label": "SeedVR2", "score": 1.0,
                "reason": "best detail",
            }],
            "selected": "seedvr2_upscale",
            "reason": "approved",
        }],
    }


def _manifest(enhancement: dict | None) -> dict:
    asset = {
        "id": "take:s1:take1", "type": "video", "path": "assets/video/s1-take1.mp4",
        "source_tool": "comfyui_video", "scene_id": "s1",
    }
    if enhancement is not None:
        asset["enhancement"] = enhancement
    return {"version": "1.0", "assets": [asset]}


def test_decision_log_accepts_enhancement_selection():
    jsonschema.validate(_decision("enhancement_selection"), _schema("decision_log"))


def test_decision_log_still_rejects_unknown_category():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_decision("enhancement"), _schema("decision_log"))


def test_asset_manifest_accepts_enhancement_object():
    jsonschema.validate(_manifest({
        "operation": "video_upscale",
        "model": "SeedVR2 3B FP8",
        "source_path": "assets/video/s1-take1.mp4",
        "parameters": {"resolution": 1080},
        "workflow_hash_sha256": "abc",
    }), _schema("asset_manifest"))


def test_asset_manifest_rejects_unknown_enhancement_key():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_manifest({
            "operation": "face_refine", "model": "H3-FaceRefine",
            "source_path": "assets/video/s1-take1.mp4", "unexpected": 1,
        }), _schema("asset_manifest"))
