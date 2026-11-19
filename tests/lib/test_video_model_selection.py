import json
from pathlib import Path

import jsonschema
import pytest

from lib.video_model_selection import (
    build_menu, default_routes, record_selection, render_menu, require_selected_route,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeTool:
    def __init__(self, status="available", cost=0.5):
        self._status, self._cost = status, cost

    def get_status(self):
        return type("S", (), {"value": self._status})()

    def estimate_cost(self, inputs):
        return self._cost

    def get_info(self):
        return {"install_instructions": "start the ComfyUI server"}


class FakeRegistry:
    def __init__(self):
        self._tools = {
            "comfyui_video": FakeTool("unavailable", 0.0),
            "minimax_video": FakeTool("available", 0.65),
        }


def test_routes_cover_local_and_cloud_paths():
    ids = {route.route_id for route in default_routes()}
    assert {"hyperflow_gguf", "hyperflow_int8", "h3_local", "minimax_direct",
            "atlas_h3", "comfyui_h3_api", "h3_max", "pika_h3_flex",
            "seedance_fal", "atlas_seedance"} <= ids


def test_menu_orders_local_first_and_reads_status():
    menu = build_menu(FakeRegistry())
    assert [item["route_id"] for item in menu[:3]] == ["hyperflow_gguf", "hyperflow_int8", "h3_local"]
    assert menu[0]["available"] is False
    assert "ComfyUI" in menu[0]["setup"]
    direct = next(item for item in menu if item["route_id"] == "minimax_direct")
    assert direct["available"] is True and direct["cost_5s"] == 0.65
    assert "hyperflow_gguf" in render_menu(menu)


def test_require_selected_route_raises_without_approval():
    with pytest.raises(ValueError, match="No user-approved"):
        require_selected_route({"decisions": []}, "hyperflow_gguf")


def test_record_selection_appends_and_validates(tmp_path):
    path = tmp_path / "decision_log.json"
    local_options = [{"option_id": "hyperflow_gguf", "label": "HyperFlow GGUF", "score": 1.0, "reason": "local first"}]
    cloud_options = [
        {"option_id": "hyperflow_gguf", "label": "HyperFlow GGUF", "score": 0.6, "reason": "local OOM"},
        {"option_id": "atlas_h3", "label": "Atlas H3", "score": 1.0, "reason": "local OOM fallback"},
    ]
    record_selection(path, "film", "assets", {"route_id": "hyperflow_gguf"}, local_options, "local first")
    record_selection(path, "film", "assets", {"route_id": "atlas_h3"}, cloud_options, "local OOM")
    log = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/artifacts/decision_log.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(log, schema)
    assert len(log["decisions"]) == 2
    assert require_selected_route(log, "atlas_h3")["selected"] == "atlas_h3"
