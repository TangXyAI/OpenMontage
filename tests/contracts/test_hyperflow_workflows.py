import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / "tools" / "_comfyui" / "workflows"
CASES = {
    "hyperflow_int8_t2v_api.json": "MiniMaxH3ImageToVideo",
    "hyperflow_int8_i2v_api.json": "MiniMaxH3ImageToVideo",
    "hyperflow_int8_flf2v_api.json": "MiniMaxH3ImageToVideo",
    "hyperflow_int8_ref2v_api.json": "MiniMaxH3ReferenceToVideo",
}


def test_workflows_are_api_format_and_complete():
    for filename, node_class in CASES.items():
        data = json.loads((WORKFLOWS / filename).read_text(encoding="utf-8"))
        classes = {node["class_type"] for node in data.values()}
        assert {"HyperFlowINT8Loader", "HyperFlowSigmas", "SaveVideo", node_class} <= classes
        assert all("class_type" in node for node in data.values())


def test_reference_workflow_has_two_image_loaders():
    data = json.loads((WORKFLOWS / "hyperflow_int8_ref2v_api.json").read_text(encoding="utf-8"))
    classes = [node["class_type"] for node in data.values()]
    assert classes.count("LoadImage") >= 2


def test_provenance_recorded():
    text = (WORKFLOWS / "HYPERFLOW_PROVENANCE.md").read_text(encoding="utf-8")
    assert "BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI" in text
    assert "MiniMax H3 Community License" in text
