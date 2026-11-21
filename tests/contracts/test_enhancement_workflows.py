import json
import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / "tools" / "_comfyui" / "workflows"


def _load(name: str) -> dict:
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def _assert_api_format(workflow: dict) -> None:
    assert workflow
    for node_id, node in workflow.items():
        assert isinstance(node, dict), node_id
        assert "class_type" in node, node_id
        assert isinstance(node.get("inputs"), dict), node_id


def test_face_refine_workflow_is_clean_api_format():
    workflow = _load("enhance_face_refine_h3_api.json")
    _assert_api_format(workflow)
    required = {"1", "2", "4", "5", "6", "7", "9", "12", "16", "17", "23", "31", "108", "109"}
    assert required <= set(workflow)
    assert workflow["1"]["inputs"]["video"] == ""
    assert workflow["6"]["inputs"]["image"] == ""
    assert workflow["7"]["inputs"]["image"] == ""
    assert workflow["9"]["inputs"]["prompt"] == ""
    assert workflow["23"]["inputs"]["frame_rate"] == 24
    assert workflow["23"]["inputs"]["filename_prefix"] == "om_enhance/face_refine"


def test_seedvr2_workflow_is_clean_api_format():
    workflow = _load("enhance_seedvr2_3b_api.json")
    _assert_api_format(workflow)
    required = {"10", "13", "14", "21", "22", "23", "24"}
    assert required <= set(workflow)
    assert workflow["21"]["inputs"]["file"] == ""
    assert workflow["23"]["inputs"]["filename_prefix"] == "om_enhance/seedvr2"


def test_workflows_have_no_machine_specific_paths():
    for name in ("enhance_face_refine_h3_api.json", "enhance_seedvr2_3b_api.json"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:[\\/]", text), name
        assert "_h3-api-export" not in text, name
        assert "smoke_" not in text, name
        assert text.endswith("\n"), name
