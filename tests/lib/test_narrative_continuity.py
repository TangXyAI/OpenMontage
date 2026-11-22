from copy import deepcopy
from pathlib import Path

import pytest

from lib.narrative_continuity import (
    ContinuityValidationError,
    build_shot_context,
    continuity_mode,
    validate_scene_plan_continuity,
    validate_shot_continuity,
)


def _location_contract(location_id):
    return {
        "location_id": location_id,
        "master_angle": "From the doorway toward the workbench.",
        "camera_axis": "Door-to-bench axis.",
        "anchors": [{"id": "workbench", "position": "camera-left, midground"}],
        "lighting": {"key_source": "window", "direction": "camera-left", "shadow_direction": "right"},
        "constants": {"time_of_day": "night", "weather": "rain", "palette": "cool gray with amber practicals"},
        "allowed_changes": ["Reverse angle may move the workbench to camera-right."],
    }


def _make_shot(shot_id, scene_id, location_id, location_asset_id, location_path, *, location_summary=None, previous=None, entity=None, change=None):
    references = [{"asset_id": location_asset_id, "kind": "image", "path": location_path, "role": "location"}]
    entities = []
    if entity is not None:
        references.insert(0, {"asset_id": entity["asset_id"], "kind": "image", "path": entity["path"], "role": "identity"})
        entities.append({"entity_id": entity["entity_id"], "asset_id": entity["asset_id"], "state": entity["state"]})
    return {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "scene_context": "The courier searches the workshop.",
        "references": references,
        "location_map": location_summary or f"{location_id} — doorway, workbench camera-left, window key from camera-left.",
        "first_frame": "The courier pauses at the doorway.",
        "action_timing": "0-2s enters; 2-4s looks at the bench.",
        "optics": "35mm, medium depth of field",
        "camera": "Locked tripod",
        "style": "Naturalistic, restrained grain.",
        "continuity": {
            "contract_version": "1.0",
            "location_id": location_id,
            "previous_shot_id": previous,
            "entities": entities,
            "carried_states": [],
            "intentional_changes": [change] if change else [],
            "screen_direction": "Moves left-to-right through the doorway.",
            "gaze_targets": ["workbench"],
            "hand_prop_states": ["Right hand empty."],
        },
    }


def _fixture(tmp_path, *, declare_change=False):
    paths = {
        "hero-dry": "assets/references/hero-dry.png",
        "hero-wet": "assets/references/hero-wet.png",
        "loc-s01-master": "assets/references/loc-s01-master.png",
        "loc-s02-master": "assets/references/loc-s02-master.png",
    }
    for path in paths.values():
        file_path = tmp_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"image")

    location_ids = {"s01": "loc-workshop", "s02": "loc-alley"}
    scene_plan = {
        "version": "1.0",
        "scenes": [
            {"id": "s01", "type": "generated", "description": "Workshop search", "start_seconds": 0, "end_seconds": 8},
            {"id": "s02", "type": "generated", "description": "Rain outside", "start_seconds": 8, "end_seconds": 12},
        ],
        "metadata": {
            "continuity_scene_ids": ["s01", "s02"],
            "location_map": {
                "s01": "loc-workshop — doorway, workbench camera-left, window key from camera-left.",
                "s02": "loc-alley — brick wall camera-right, streetlamp behind camera.",
            },
            "scene_continuity": {
                "s01": _location_contract("loc-workshop"),
                "s02": {**_location_contract("loc-alley"), "master_angle": "Along the alley toward the fire escape."},
            },
        },
    }

    hero_dry = {
        "kind": "character", "entity_id": "hero", "description": "Courier in an olive coat with a silver key.",
        "path": paths["hero-dry"], "state": "dry", "metadata": {},
    }
    hero_wet = {
        "kind": "character", "entity_id": "hero", "description": "Courier in the same olive coat, soaked by rain.",
        "path": paths["hero-wet"], "state": "wet", "metadata": {},
    }
    location_s01 = {
        "kind": "location", "entity_id": "loc-workshop", "description": "Empty workshop master plate.",
        "path": paths["loc-s01-master"], "state": "master_plate", "metadata": {},
    }
    location_s02 = {
        "kind": "location", "entity_id": "loc-alley", "description": "Empty rain alley master plate.",
        "path": paths["loc-s02-master"], "state": "master_plate", "metadata": {},
    }

    shot_1 = _make_shot(
        "s01-sh01", "s01", "loc-workshop", "loc-s01-master", paths["loc-s01-master"],
        entity={"entity_id": "hero", "asset_id": "hero-dry", "state": "dry", "path": paths["hero-dry"]},
    )
    shot_2 = _make_shot("s01-sh02", "s01", "loc-workshop", "loc-s01-master", paths["loc-s01-master"], previous="s01-sh01")
    change = {"entity_id": "hero", "from_state": "dry", "to_state": "wet", "reason": "Rain begins between scenes."} if declare_change else None
    shot_3 = _make_shot(
        "s02-sh01", "s02", "loc-alley", "loc-s02-master", paths["loc-s02-master"],
        location_summary="loc-alley — brick wall camera-right, streetlamp behind camera.",
        previous="s01-sh02",
        entity={"entity_id": "hero", "asset_id": "hero-wet", "state": "wet", "path": paths["hero-wet"]},
        change=change,
    )
    shots = [shot_1, shot_2, shot_3]
    catalog_data = {
        "assets": {
            "hero-dry": hero_dry,
            "hero-wet": hero_wet,
            "loc-s01-master": location_s01,
            "loc-s02-master": location_s02,
        },
        "shots": {
            "s01-sh01": {"scene_id": "s01", "continuity_contract_version": "1.0", "asset_ids": ["hero-dry", "loc-s01-master"]},
            "s01-sh02": {"scene_id": "s01", "continuity_contract_version": "1.0", "asset_ids": ["loc-s01-master"]},
            "s02-sh01": {"scene_id": "s02", "continuity_contract_version": "1.0", "asset_ids": ["hero-wet", "loc-s02-master"]},
        },
    }
    return scene_plan, {"version": "1.0", "shots": shots}, catalog_data


def test_strict_scene_requires_location_contract(tmp_path):
    scene_plan, _, _ = _fixture(tmp_path)
    scene_plan["metadata"]["scene_continuity"].pop("s01")
    with pytest.raises(ContinuityValidationError, match="s01"):
        validate_scene_plan_continuity(scene_plan, strict=True)


def test_legacy_mode_skips_new_continuity_requirements():
    assert continuity_mode({}) == "legacy"
    assert continuity_mode({"metadata": {"continuity_contract_version": "1.0"}}) == "strict"
    with pytest.raises(ContinuityValidationError, match="unsupported"):
        continuity_mode({"metadata": {"continuity_contract_version": "2.0"}})

    validate_shot_continuity({"version": "1.0", "scenes": []}, {"version": "1.0", "shots": []}, {}, Path("."), strict=False)


def test_opted_in_project_keeps_approved_legacy_scene_unmarked(tmp_path):
    scene_plan, shot_specs, catalog_data = _fixture(tmp_path, declare_change=True)
    scene_plan["metadata"]["continuity_scene_ids"] = ["s01"]
    scene_plan["metadata"]["scene_continuity"].pop("s02")
    shot_specs["shots"][2].pop("continuity")
    catalog_data["shots"]["s02-sh01"].pop("continuity_contract_version")

    validate_scene_plan_continuity(scene_plan, strict=True)
    validate_shot_continuity(scene_plan, shot_specs, catalog_data, tmp_path, strict=True)


def test_nonadjacent_entity_state_change_requires_declared_delta(tmp_path):
    scene_plan, shot_specs, catalog_data = _fixture(tmp_path)
    with pytest.raises(ContinuityValidationError, match="hero.*state"):
        validate_shot_continuity(scene_plan, shot_specs, catalog_data, tmp_path, strict=True)


def test_shot_with_unknown_scene_or_asset_fails_before_generation(tmp_path):
    scene_plan, shot_specs, catalog_data = _fixture(tmp_path)
    shot_specs["shots"][0]["scene_id"] = "unknown-scene"
    with pytest.raises(ContinuityValidationError, match="scene_id|asset_id"):
        validate_shot_continuity(scene_plan, shot_specs, catalog_data, tmp_path, strict=True)


def test_reference_missing_mismatched_or_outside_project_fails_before_generation(tmp_path):
    scene_plan, shot_specs, catalog_data = _fixture(tmp_path)
    shot_specs["shots"][0]["references"][0]["path"] = "assets/missing.png"
    with pytest.raises(ContinuityValidationError, match="reference path"):
        validate_shot_continuity(scene_plan, shot_specs, catalog_data, tmp_path, strict=True)

    mismatch_root = tmp_path / "mismatch"
    mismatch_scene_plan, mismatched_shots, catalog_data = _fixture(mismatch_root)
    mismatched_shots["shots"][0]["references"][0]["path"] = catalog_data["assets"]["loc-s01-master"]["path"]
    with pytest.raises(ContinuityValidationError, match="reference path"):
        validate_shot_continuity(mismatch_scene_plan, mismatched_shots, catalog_data, mismatch_root, strict=True)

    scene_plan, shot_specs, catalog_data = _fixture(tmp_path / "outside")
    outside = tmp_path.parent / "outside-reference.png"
    outside.write_bytes(b"outside")
    shot_specs["shots"][0]["references"][0]["path"] = str(outside)
    with pytest.raises(ContinuityValidationError, match="reference path"):
        validate_shot_continuity(scene_plan, shot_specs, catalog_data, tmp_path, strict=True)


def test_missing_approved_location_plate_reference_fails(tmp_path):
    scene_plan, shot_specs, catalog_data = _fixture(tmp_path)
    shot_specs["shots"][0]["references"] = [ref for ref in shot_specs["shots"][0]["references"] if ref["role"] != "location"]
    with pytest.raises(ContinuityValidationError, match="master plate"):
        validate_shot_continuity(scene_plan, shot_specs, catalog_data, tmp_path, strict=True)


def test_intentional_nonadjacent_state_change_passes(tmp_path):
    scene_plan, shot_specs, catalog_data = _fixture(tmp_path, declare_change=True)
    validate_shot_continuity(scene_plan, shot_specs, catalog_data, tmp_path, strict=True)


def test_context_copies_descriptor_and_role_labeled_references(tmp_path):
    _, shot_specs, catalog_data = _fixture(tmp_path)
    shot = shot_specs["shots"][0]
    scene_contract = _location_contract("loc-workshop")
    context = build_shot_context(shot, scene_contract, catalog_data, tmp_path)

    assert context["stable_descriptors"][0]["text"] == "Courier in an olive coat with a silver key."
    assert {ref["role"] for ref in context["references"]} == {"identity", "location"}
