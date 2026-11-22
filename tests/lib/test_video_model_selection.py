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
    def __init__(self, comfyui_status="unavailable"):
        self._tools = {
            "comfyui_video": FakeTool(comfyui_status, 0.0),
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


def _variant(ready, blockers=()):
    return {
        "ready": ready,
        "fl2va": None,
        "ref2va": None,
        "blockers": list(blockers),
    }


def _readiness(*, gguf_ready=False, int8_ready=True):
    variants = {
        "gguf": _variant(
            gguf_ready,
            ()
            if gguf_ready
            else [
                "Missing HyperFlow fl2va GGUF checkpoint "
                "'*hyperflow*fl2va*.gguf' in model roots: G:/models"
            ],
        ),
        "int8": _variant(
            int8_ready,
            ()
            if int8_ready
            else [
                "Missing HyperFlow fl2va INT8 checkpoint "
                "'*14b-int8_convrot.safetensors' in model roots: "
                "G:/models"
            ],
        ),
    }
    ready_variants = [
        name for name, state in variants.items() if state["ready"]
    ]
    return {
        "ready": bool(ready_variants),
        "ready_variants": ready_variants,
        "variants": variants,
    }


def test_menu_uses_readiness_per_quantization_variant():
    menu = build_menu(FakeRegistry("available"), readiness=_readiness())
    gguf = next(item for item in menu if item["route_id"] == "hyperflow_gguf")
    int8 = next(item for item in menu if item["route_id"] == "hyperflow_int8")
    assert gguf["available"] is False
    assert gguf["status"] == "unavailable"
    assert "gguf" in gguf["setup"].lower()
    assert "ComfyUI" not in gguf["setup"]
    assert int8["available"] is True
    assert int8["status"] == "available"
    assert int8["setup"] is None


def test_ready_weights_with_unavailable_tool_are_not_available():
    menu = build_menu(FakeRegistry(), readiness=_readiness())
    int8 = next(item for item in menu if item["route_id"] == "hyperflow_int8")
    assert int8["available"] is False
    assert int8["status"] == "unavailable"
    assert "ComfyUI" in int8["setup"]


def test_missing_weights_and_missing_tool_both_appear_in_setup():
    menu = build_menu(
        FakeRegistry(),
        readiness=_readiness(gguf_ready=False, int8_ready=False),
    )
    gguf = next(item for item in menu if item["route_id"] == "hyperflow_gguf")
    assert gguf["available"] is False
    assert "Missing HyperFlow" in gguf["setup"]
    assert "ComfyUI" in gguf["setup"]
    assert "; ;" not in gguf["setup"]
    assert not gguf["setup"].endswith(";")


def test_menu_keeps_tool_status_for_h3_local_with_readiness():
    menu = build_menu(FakeRegistry(), readiness=_readiness())
    h3_local = next(item for item in menu if item["route_id"] == "h3_local")
    assert h3_local["available"] is False
    assert "ComfyUI" in h3_local["setup"]


def test_menu_readiness_leaves_cloud_routes_unchanged():
    menu = build_menu(FakeRegistry(), readiness=_readiness())
    direct = next(item for item in menu if item["route_id"] == "minimax_direct")
    assert direct["available"] is True
    assert direct["cost_5s"] == 0.65


def test_menu_marks_gguf_available_when_its_variant_is_ready():
    menu = build_menu(
        FakeRegistry("available"), readiness=_readiness(gguf_ready=True, int8_ready=False)
    )
    gguf = next(item for item in menu if item["route_id"] == "hyperflow_gguf")
    int8 = next(item for item in menu if item["route_id"] == "hyperflow_int8")
    assert gguf["available"] is True and gguf["setup"] is None
    assert int8["available"] is False
    assert "int8" in int8["setup"].lower()


def test_video_menu_uses_explicit_server_for_local_h3_only(monkeypatch):
    import lib.video_model_selection as module

    seen = []

    class SelectedServer:
        def __init__(self, server_url=None, capability=None):
            seen.append((server_url, capability))

        def is_available(self):
            return True

    monkeypatch.setattr(module, "ComfyUIClient", SelectedServer, raising=False)

    menu = build_menu(FakeRegistry("unavailable"), server_url="http://127.0.0.1:8290")
    routes = {item["route_id"]: item for item in menu}

    assert routes["h3_local"]["available"] is True
    assert routes["hyperflow_int8"]["available"] is True
    assert routes["comfyui_h3_api"]["available"] is False
    assert seen == [("http://127.0.0.1:8290", "video")]


def test_require_selected_route_raises_without_approval():
    with pytest.raises(ValueError, match="No user-approved"):
        require_selected_route({"decisions": []}, "hyperflow_gguf")


def test_custom_subject_keeps_route_and_variant_decisions_separate(tmp_path):
    path = tmp_path / "decision_log.json"
    options = [
        {"option_id": "hyperflow_int8", "label": "HyperFlow INT8", "score": 1.0,
         "reason": "local"}
    ]
    record_selection(path, "film", "proposal", {"route_id": "hyperflow_int8"},
                     options, "local route", subject="Local H3 variant")
    record_selection(path, "film", "proposal", {"route_id": "hyperflow_int8"},
                     options, "route-level approval")
    log = json.loads(path.read_text(encoding="utf-8"))
    assert require_selected_route(
        log, "hyperflow_int8", subject="Local H3 variant"
    )["selected"] == "hyperflow_int8"
    assert require_selected_route(log, "hyperflow_int8")["selected"] == "hyperflow_int8"


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
