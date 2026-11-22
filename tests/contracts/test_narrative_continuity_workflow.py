from pathlib import Path

import pytest

from lib.checkpoint import init_project, write_checkpoint
from lib.narrative_assets import NarrativeAssets
from lib.narrative_continuity import validate_shot_continuity
from tests.contracts.test_phase0_contracts import sample_artifact
from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose


def _write_media(root: Path, *paths: str) -> None:
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"media")


def _review(root: Path, shot_id: str, *, status: str = "pass", override_reason: str | None = None) -> dict:
    evidence = f"assets/reviews/{shot_id}.png"
    _write_media(root, evidence)
    dimensions = {
        "identity_wardrobe": "pass",
        "location_anchors": "pass",
        "camera_continuity": "pass",
        "light_and_look": "pass",
        "story_state": "pass",
    }
    dimensions["location_anchors"] = status
    review = {
        "dimensions": dimensions,
        "notes": {key: "Checked against the approved continuity contract." for key in dimensions},
        "evidence_paths": [evidence],
    }
    if override_reason is not None:
        review["override_reason"] = override_reason
    return review


def _proposal_checkpoint(tmp_path: Path, *, strict: bool) -> Path:
    root = init_project("film", title="Continuity pilot", pipeline_type="cinematic", pipeline_dir=tmp_path)
    write_checkpoint(
        tmp_path, "film", "research", "completed",
        {"research_brief": sample_artifact("research_brief")}, pipeline_type="cinematic",
    )
    proposal = sample_artifact("proposal_packet")
    proposal["production_plan"]["pipeline"] = "cinematic"
    if strict:
        proposal.setdefault("metadata", {})["continuity_contract_version"] = "1.0"
    write_checkpoint(
        tmp_path, "film", "proposal", "completed", {"proposal_packet": proposal},
        pipeline_type="cinematic", human_approved=True,
    )
    return root


def _write_asset_and_edit_checkpoints(tmp_path: Path, manifest: dict, edit: dict, *, scene_plan: dict | None = None) -> None:
    write_checkpoint(
        tmp_path, "film", "script", "completed", {"script": sample_artifact("script")},
        pipeline_type="cinematic", human_approved=True,
    )
    write_checkpoint(
        tmp_path, "film", "scene_plan", "completed", {"scene_plan": scene_plan or sample_artifact("scene_plan")},
        pipeline_type="cinematic", human_approved=True,
    )
    write_checkpoint(
        tmp_path, "film", "assets", "completed", {"asset_manifest": manifest},
        pipeline_type="cinematic", human_approval_required=True, human_approved=True,
    )
    write_checkpoint(tmp_path, "film", "edit", "completed", {"edit_decisions": edit}, pipeline_type="cinematic")


def _compose_result(root: Path, manifest: dict, edit: dict) -> ToolResult:
    tool = VideoCompose()
    tool._compose = lambda inputs: ToolResult(success=True)
    return tool.execute({
        "operation": "compose",
        "project_dir": str(root),
        "edit_decisions": edit,
        "asset_manifest": manifest,
        "output_path": str(root / "renders" / "out.mp4"),
    })


def _one_shot_catalog(root: Path, *, strict: bool, review_status: str | None = None, override_reason: str | None = None):
    _write_media(
        root,
        "assets/images/hero.png",
        "assets/images/location.png",
        "assets/video/take-a.mp4",
    )
    catalog = NarrativeAssets(root)
    catalog.put_asset("hero", "character", "Courier in an olive coat.", "assets/images/hero.png", entity_id="hero")
    catalog.put_asset("loc-master", "location", "Empty workshop plate.", "assets/images/location.png", state="master_plate", entity_id="loc-workshop")
    catalog.register_shot("s01-sh01", "s01", continuity_contract_version="1.0" if strict else None)
    catalog.link_assets("s01-sh01", ["hero", "loc-master"])
    catalog.add_take("s01-sh01", "take-a", "assets/video/take-a.mp4", 4.0)
    if review_status is not None:
        catalog.record_continuity_review(
            "s01-sh01", "take-a", _review(root, "s01-sh01", status=review_status, override_reason=override_reason),
        )
    if not strict or review_status is not None:
        catalog.select_take("s01-sh01", "take-a")
    return catalog


def test_compose_rejects_review_for_pre_enhancement_path(tmp_path):
    root = _proposal_checkpoint(tmp_path, strict=True)
    catalog = _one_shot_catalog(root, strict=True, review_status="pass")
    old_manifest = catalog.asset_manifest()
    old_edit = catalog.edit_decisions(["s01-sh01"], "ffmpeg")
    _write_asset_and_edit_checkpoints(tmp_path, old_manifest, old_edit)

    _write_media(root, "assets/video/enhanced/take-a.mp4")
    catalog.apply_enhancement(
        "s01-sh01", "take-a", "assets/video/enhanced/take-a.mp4", duration_seconds=4.0,
        enhancement={"operation": "relayvsr", "model": "RelayVSR", "source_path": "assets/video/take-a.mp4"},
    )

    result = _compose_result(root, old_manifest, old_edit)
    assert not result.success
    assert "stale" in result.error.lower() or "continuity review" in result.error.lower()


def test_compose_allows_legacy_selection_without_continuity_review(tmp_path):
    root = _proposal_checkpoint(tmp_path, strict=False)
    catalog = _one_shot_catalog(root, strict=False)
    catalog.select_take("s01-sh01", "take-a")
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s01-sh01"], "ffmpeg")
    _write_asset_and_edit_checkpoints(tmp_path, manifest, edit)

    result = _compose_result(root, manifest, edit)
    assert result.success, result.error


def test_compose_allows_drift_only_with_recorded_override(tmp_path):
    root = _proposal_checkpoint(tmp_path, strict=True)
    catalog = _one_shot_catalog(
        root, strict=True, review_status="drift", override_reason="Intentional dream sequence geometry.",
    )
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s01-sh01"], "ffmpeg")
    _write_asset_and_edit_checkpoints(tmp_path, manifest, edit)

    result = _compose_result(root, manifest, edit)
    assert result.success, result.error


def test_strict_narrative_pilot_preserves_state_and_review_through_compose(tmp_path):
    root = _proposal_checkpoint(tmp_path, strict=True)
    media = {
        "hero-dry": "assets/images/hero-dry.png",
        "hero-wet": "assets/images/hero-wet.png",
        "loc-s01": "assets/images/loc-s01.png",
        "loc-s02": "assets/images/loc-s02.png",
    }
    takes = {
        "s01-sh01": "assets/video/s01-sh01.mp4",
        "s01-sh02": "assets/video/s01-sh02.mp4",
        "s02-sh01": "assets/video/s02-sh01.mp4",
    }
    for path in (*media.values(), *takes.values()):
        _write_media(root, path)

    catalog = NarrativeAssets(root)
    catalog.put_asset("hero-dry", "character", "Courier, olive coat, silver key.", media["hero-dry"], state="dry", entity_id="hero")
    catalog.put_asset("hero-wet", "character", "Courier, olive coat, silver key, soaked.", media["hero-wet"], state="wet", entity_id="hero")
    catalog.put_asset("loc-s01-master", "location", "Workshop master plate.", media["loc-s01"], state="master_plate", entity_id="loc-workshop")
    catalog.put_asset("loc-s02-master", "location", "Alley master plate.", media["loc-s02"], state="master_plate", entity_id="loc-alley")

    shots = (
        ("s01-sh01", "s01", "loc-workshop", "loc-s01-master", "hero-dry", "dry", None, []),
        ("s01-sh02", "s01", "loc-workshop", "loc-s01-master", None, None, "s01-sh01", []),
        ("s02-sh01", "s02", "loc-alley", "loc-s02-master", "hero-wet", "wet", "s01-sh02", [
            {"entity_id": "hero", "from_state": "dry", "to_state": "wet", "reason": "Rain begins between scenes."},
        ]),
    )
    scene_contracts = {
        "s01": {"location_id": "loc-workshop", "master_angle": "Door to workbench.", "camera_axis": "Door-to-bench", "anchors": [{"id": "bench", "position": "camera-left"}], "lighting": {"key_source": "window", "direction": "left", "shadow_direction": "right"}},
        "s02": {"location_id": "loc-alley", "master_angle": "Along the alley.", "camera_axis": "Street axis", "anchors": [{"id": "fire-escape", "position": "rear-right"}], "lighting": {"key_source": "streetlamp", "direction": "rear", "shadow_direction": "foreground"}},
    }
    scene_plan = {
        "version": "1.0",
        "scenes": [
            {"id": "s01", "type": "generated", "description": "Workshop", "start_seconds": 0, "end_seconds": 8},
            {"id": "s02", "type": "generated", "description": "Rain alley", "start_seconds": 8, "end_seconds": 12},
        ],
        "metadata": {
            "continuity_scene_ids": ["s01", "s02"],
            "scene_continuity": scene_contracts,
            "location_map": {
                "s01": "loc-workshop — Door to workbench, bench camera-left, window key from left.",
                "s02": "loc-alley — Along the alley, fire escape rear-right, streetlamp from rear.",
            },
        },
    }

    shot_specs = []
    for shot_id, scene_id, location_id, location_asset_id, hero_asset_id, hero_state, previous, changes in shots:
        contract = scene_contracts[scene_id]
        location_summary = scene_plan["metadata"]["location_map"][scene_id]
        refs = [{"asset_id": location_asset_id, "kind": "image", "path": media["loc-s01" if scene_id == "s01" else "loc-s02"], "role": "location"}]
        entities = []
        linked = [location_asset_id]
        if hero_asset_id:
            refs.insert(0, {"asset_id": hero_asset_id, "kind": "image", "path": media[hero_asset_id], "role": "identity"})
            entities.append({"entity_id": "hero", "asset_id": hero_asset_id, "state": hero_state})
            linked.insert(0, hero_asset_id)
        catalog.register_shot(shot_id, scene_id, continuity_contract_version="1.0")
        catalog.link_assets(shot_id, linked)
        catalog.add_take(shot_id, "take-1", takes[shot_id], 4.0)
        catalog.record_continuity_review(shot_id, "take-1", _review(root, shot_id))
        catalog.select_take(shot_id, "take-1")
        shot_specs.append({
            "shot_id": shot_id,
            "scene_id": scene_id,
            "references": refs,
            "location_map": location_summary,
            "first_frame": "Courier at the doorway.",
            "scene_context": "Courier searches for the parcel.",
            "action_timing": "0-2s enters; 2-4s searches.",
            "camera": "Locked tripod.",
            "optics": "35mm.",
            "style": "Naturalistic.",
            "constraints": "No text.",
            "continuity": {
                "contract_version": "1.0",
                "location_id": location_id,
                "previous_shot_id": previous,
                "entities": entities,
                "carried_states": [],
                "intentional_changes": changes,
                "screen_direction": "Left-to-right.",
                "gaze_targets": [],
                "hand_prop_states": [],
            },
        })

    validate_shot_continuity(scene_plan, {"version": "1.0", "shots": shot_specs}, catalog.data, root, strict=True)
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions([shot_id for shot_id, *_ in shots], "ffmpeg")
    assert [item["scene_id"] for item in manifest["assets"] if item["type"] == "video"] == ["s01", "s01", "s02"]
    assert [item["scene_id"] for item in edit["metadata"]["continuity_shots"].values()] == ["s01", "s01", "s02"]
    _write_asset_and_edit_checkpoints(tmp_path, manifest, edit, scene_plan=scene_plan)

    result = _compose_result(root, manifest, edit)
    assert result.success, result.error
