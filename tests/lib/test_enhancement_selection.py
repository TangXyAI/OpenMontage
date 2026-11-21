import json

import pytest

from lib.enhancement_selection import (
    ENHANCEMENT_SUBJECT,
    build_menu,
    record_selection,
    require_selected_route,
)


class FakeTool:
    def get_status(self):
        class S:
            value = "available"
        return S()


class FakeRegistry:
    def __init__(self, tools):
        self._tools = tools


def _readiness(face=True, upscale=True, server=True):
    return {
        "ready": face and upscale and server,
        "server_running": server,
        "routes": {
            "face_refine": {"ready": face, "blockers": [] if face else ["missing FaceRefine node"], "warnings": []},
            "video_upscale": {"ready": upscale, "blockers": [] if upscale else ["missing SeedVR2 VAE"], "warnings": []},
        },
    }


def test_menu_order_and_none_always_available():
    menu = build_menu(FakeRegistry({"comfyui_enhance": FakeTool()}), _readiness(face=False, upscale=False, server=False), duration_seconds=7.0)
    assert [row["route_id"] for row in menu] == ["none", "face_refine", "seedvr2_upscale"]
    assert menu[0]["available"] is True
    assert menu[1]["available"] is False
    assert menu[2]["available"] is False


def test_missing_tool_marks_routes_unavailable():
    menu = build_menu(FakeRegistry({}), _readiness(), duration_seconds=7.0)
    assert menu[1]["available"] is False
    assert "not registered" in menu[1]["reason"]


def test_duration_drives_estimate():
    menu = build_menu(FakeRegistry({"comfyui_enhance": FakeTool()}), _readiness(), duration_seconds=3.04)
    assert menu[2]["estimated_seconds"] == round(30 + 178 * 3.04)
    assert menu[1]["estimate_source"] == "placeholder"


def test_menu_rows_carry_status_and_route_warnings():
    readiness = _readiness()
    warning = "SeedVR2 3B DiT missing; first run downloads ~3.16 GB"
    readiness["routes"]["video_upscale"]["warnings"] = [warning]
    menu = build_menu(
        FakeRegistry({"comfyui_enhance": FakeTool()}),
        readiness,
        duration_seconds=3.04,
    )
    rows = {row["route_id"]: row for row in menu}

    seedvr2 = rows["seedvr2_upscale"]
    assert seedvr2["status"] == "available"
    assert warning in seedvr2["warnings"]
    assert "3.16 GB" in " ".join(seedvr2["warnings"])

    none = rows["none"]
    assert none["status"] == "available"
    assert none["warnings"] == []


def test_menu_delegates_estimate_to_the_registered_tool():
    class EstimatingTool(FakeTool):
        def estimate_runtime(self, inputs):
            return 1000.0 + inputs["duration_seconds"]

    menu = build_menu(
        FakeRegistry({"comfyui_enhance": EstimatingTool()}),
        _readiness(),
        duration_seconds=4.0,
    )
    assert menu[1]["estimated_seconds"] == 1004
    assert menu[2]["estimated_seconds"] == 1004


def test_menu_merges_and_deduplicates_shared_warnings():
    readiness = _readiness()
    route_warning = "route warning"
    shared_warning = "shared warning"
    readiness["routes"]["video_upscale"]["warnings"] = [route_warning, shared_warning]
    readiness["warnings"] = [shared_warning, "other shared warning"]
    menu = build_menu(
        FakeRegistry({"comfyui_enhance": FakeTool()}),
        readiness,
        duration_seconds=1.0,
    )
    warnings = next(
        row for row in menu if row["route_id"] == "seedvr2_upscale"
    )["warnings"]
    assert warnings.count(shared_warning) == 1
    assert route_warning in warnings
    assert "other shared warning" in warnings


def test_record_and_require_selection(tmp_path):
    path = tmp_path / "decision_log.json"
    options = [
        {"option_id": "none", "label": "No enhancement", "score": 0.5, "reason": "cheap"},
        {"option_id": "seedvr2_upscale", "label": "SeedVR2", "score": 1.0, "reason": "detail"},
    ]
    record_selection(str(path), "p", "assets", "seedvr2_upscale", options, "approved")
    log = json.loads(path.read_text(encoding="utf-8"))
    decision = log["decisions"][-1]
    assert decision["category"] == "enhancement_selection"
    assert decision["subject"] == ENHANCEMENT_SUBJECT
    assert decision["user_approved"] is True
    assert require_selected_route(log, "seedvr2_upscale")["selected"] == "seedvr2_upscale"
    with pytest.raises(ValueError):
        require_selected_route(log, "face_refine")


def test_record_rejects_route_outside_options(tmp_path):
    path = tmp_path / "d.json"
    with pytest.raises(ValueError):
        record_selection(str(path), "p", "assets", "missing", [{"option_id": "none"}], "x")
    assert not path.exists()
