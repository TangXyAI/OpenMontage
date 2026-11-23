import json

from lib.enhancement_selection import build_menu, record_selection, require_selected_route
from lib.local_enhancement_readiness import check_enhancement_readiness


def test_relayvsr_readiness_and_menu(tmp_path):
    root = tmp_path / "comfy"
    (root / "comfy_extras").mkdir(parents=True)
    (root / "comfyui_version.py").write_text('__version__ = "0.45.0"')
    (root / "comfy_extras" / "nodes_wan.py").write_text(
        "class RelayVSRConditioning: pass\nclass VSRDecode: pass\n"
    )
    models = tmp_path / "models"
    models.mkdir()
    for name in ("relayvsr_x2_lightx2v_int8_convrot.safetensors", "relayvsr_flash_vae_x2_fp32.safetensors"):
        (models / name).touch()
    readiness = check_enhancement_readiness(root, [models], server_running=True)
    assert readiness["routes"]["relayvsr"]["ready"] is True

    class Tool:
        def get_status(self):
            return "available"

    class Registry:
        _tools = {"comfyui_enhance": Tool()}

    rows = {row["route_id"]: row for row in build_menu(Registry(), readiness)}
    assert rows["relayvsr_upscale"]["operation"] == "relayvsr"
    assert rows["relayvsr_upscale"]["available"] is True
    assert rows["relayvsr_upscale"]["recommended"] is True


def test_relayvsr_missing_model_is_blocked(tmp_path):
    root = tmp_path / "comfy"
    (root / "comfy_extras").mkdir(parents=True)
    (root / "comfyui_version.py").write_text('__version__ = "0.45.0"')
    (root / "comfy_extras" / "nodes_wan.py").write_text(
        "class RelayVSRConditioning: pass\nclass VSRDecode: pass\n"
    )
    models = tmp_path / "models"
    models.mkdir()
    readiness = check_enhancement_readiness(root, [models], server_running=True)
    assert readiness["routes"]["relayvsr"]["ready"] is False


def test_relayvsr_missing_core_nodes_is_blocked(tmp_path):
    root = tmp_path / "comfy"
    root.mkdir()
    (root / "comfyui_version.py").write_text('__version__ = "0.45.0"')
    models = tmp_path / "models"
    models.mkdir()
    for name in ("relayvsr_x2_lightx2v_int8_convrot.safetensors", "relayvsr_flash_vae_x2_fp32.safetensors"):
        (models / name).touch()
    readiness = check_enhancement_readiness(root, [models], server_running=True)
    assert readiness["routes"]["relayvsr"]["ready"] is False
    assert "core nodes" in " ".join(readiness["routes"]["relayvsr"]["blockers"])


def test_relayvsr_can_be_recorded_as_the_selected_route(tmp_path):
    path = tmp_path / "decision.json"
    options = [{"option_id": "relayvsr_upscale", "label": "RelayVSR", "score": 1.0, "reason": "default"}]
    record_selection(path, "project", "assets", "relayvsr_upscale", options, "selected")
    assert require_selected_route(json.loads(path.read_text(encoding="utf-8")), "relayvsr_upscale")
