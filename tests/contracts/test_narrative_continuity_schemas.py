import copy
import json
from pathlib import Path

import jsonschema
import pytest

from tests.contracts.test_phase0_contracts import sample_artifact


ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict:
    return json.loads((ROOT / f"schemas/artifacts/{name}.schema.json").read_text(encoding="utf-8"))


PROPOSAL_SCHEMA = _schema("proposal_packet")
SCENE_PLAN_SCHEMA = _schema("scene_plan")
SHOT_SPEC_SCHEMA = _schema("shot_spec")


def _shot_spec() -> dict:
    return {
        "version": "1.0",
        "shots": [{
            "shot_id": "s01-sh01",
            "scene_id": "s01",
            "duration_seconds": 4,
            "scene_context": "A courier enters the workshop.",
            "references": [{"asset_id": "hero-wet", "kind": "image", "path": "assets/hero-wet.png", "role": "identity"}],
            "location_map": "Door rear-center; workbench camera-left; key light from the window.",
            "first_frame": "The courier stands just inside the doorway.",
            "format_mode": "single take",
            "optics": "35mm, medium depth of field",
            "camera": "locked tripod",
            "action_timing": "0-2s enters; 2-4s looks toward the bench.",
            "physics": "Coat remains wet and heavy.",
            "lighting": "Window key from camera-left, shadows fall right.",
            "audio": "Room tone only.",
            "character_acting": "Objective: find the parcel.",
            "style": "Naturalistic, restrained grain.",
            "quality": "Face and hands remain readable.",
            "constraints": "No on-screen text.",
            "continuity": {
                "contract_version": "1.0",
                "location_id": "loc-workshop",
                "previous_shot_id": None,
                "entities": [{"entity_id": "hero", "asset_id": "hero-wet", "state": "wet"}],
                "carried_states": ["The coat is wet."],
                "intentional_changes": [],
                "screen_direction": "Moves left-to-right through the doorway.",
                "gaze_targets": ["workbench"],
                "hand_prop_states": ["Right hand empty."],
            },
        }],
    }


def _scene_plan() -> dict:
    scene_plan = sample_artifact("scene_plan")
    scene_id = scene_plan["scenes"][0]["id"]
    scene_plan["metadata"] = {
        "continuity_scene_ids": [scene_id],
        "location_map": {
            scene_id: "Door rear-center; workbench camera-left; window key from camera-left, shadows fall right."
        },
        "scene_continuity": {
            scene_id: {
                "location_id": "loc-workshop",
                "master_angle": "From the doorway toward the workbench.",
                "camera_axis": "Door-to-bench axis.",
                "anchors": [{"id": "workbench", "position": "camera-left, midground"}],
                "lighting": {"key_source": "window", "direction": "camera-left", "shadow_direction": "right"},
                "constants": {"time_of_day": "night", "weather": "rain", "palette": "cool gray with amber practicals"},
                "allowed_changes": ["Reverse angle may move the workbench to camera-right."],
            }
        },
    }
    return scene_plan


def test_continuity_version_is_optional_for_legacy_proposals():
    legacy_proposal = sample_artifact("proposal_packet")
    jsonschema.validate(legacy_proposal, PROPOSAL_SCHEMA)

    versioned_proposal = copy.deepcopy(legacy_proposal)
    versioned_proposal.setdefault("metadata", {})["continuity_contract_version"] = "1.0"
    jsonschema.validate(versioned_proposal, PROPOSAL_SCHEMA)


def test_continuity_version_rejects_unknown_value():
    proposal = sample_artifact("proposal_packet")
    proposal.setdefault("metadata", {})["continuity_contract_version"] = "2.0"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(proposal, PROPOSAL_SCHEMA)


def test_scene_continuity_requires_typed_anchors_and_lighting():
    scene_plan = _scene_plan()
    jsonschema.validate(scene_plan, SCENE_PLAN_SCHEMA)

    malformed = copy.deepcopy(scene_plan)
    scene_id = malformed["scenes"][0]["id"]
    del malformed["metadata"]["scene_continuity"][scene_id]["anchors"][0]["position"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(malformed, SCENE_PLAN_SCHEMA)


def test_legacy_scene_plan_without_continuity_remains_valid():
    jsonschema.validate(sample_artifact("scene_plan"), SCENE_PLAN_SCHEMA)


def test_continuity_scene_ids_must_be_unique_strings():
    scene_plan = _scene_plan()
    jsonschema.validate(scene_plan, SCENE_PLAN_SCHEMA)

    malformed = copy.deepcopy(scene_plan)
    scene_id = malformed["scenes"][0]["id"]
    malformed["metadata"]["continuity_scene_ids"] = [scene_id, scene_id]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(malformed, SCENE_PLAN_SCHEMA)


def test_shot_continuity_requires_entity_and_change_fields():
    shot_spec = _shot_spec()
    jsonschema.validate(shot_spec, SHOT_SPEC_SCHEMA)

    malformed = copy.deepcopy(shot_spec)
    del malformed["shots"][0]["continuity"]["entities"][0]["entity_id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(malformed, SHOT_SPEC_SCHEMA)
