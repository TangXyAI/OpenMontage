import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/artifacts/shot_spec.schema.json").read_text(encoding="utf-8"))

SAMPLE = {
    "version": "1.0",
    "shots": [{
        "shot_id": "shot-01", "scene_id": "scene-01", "duration_seconds": 5,
        "scene_context": "Ron calls Adam from his office.",
        "references": [{"asset_id": "hero", "kind": "image", "path": "assets/references/hero.png", "role": "identity"}],
        "location_map": "Desk spans the frame; camera on Ron's right.",
        "first_frame": "Close-up of Ron's mouth and the receiver.",
        "format_mode": "single take, real time",
        "optics": "47-degree diagonal field of view",
        "camera": "tripod, slow push-in",
        "action_timing": "0-2s Ron speaks; 2-5s he slams the receiver.",
        "physics": "Receiver cable snaps taut; ash jumps.",
        "lighting": "Single banker's lamp, warm, from frame left.",
        "audio": "Room tone, receiver click, no music.",
        "character_acting": "Objective: force Adam to act. Obstacle: guilt.",
        "style": "Neo-noir, 35mm grain, anamorphic flare.",
        "quality": "Face and hands readable at key beats.",
        "constraints": "One character; no on-screen text.",
    }],
}


def test_complete_spec_is_valid():
    jsonschema.validate(SAMPLE, SCHEMA)


def test_provider_specific_field_is_rejected():
    bad = copy.deepcopy(SAMPLE)
    bad["shots"][0]["model_version"] = "2.5"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
