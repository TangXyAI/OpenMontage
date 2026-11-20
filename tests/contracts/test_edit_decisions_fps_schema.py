import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "schemas/artifacts/edit_decisions.schema.json").read_text(encoding="utf-8")
)

SAMPLE = {
    "version": "1.0",
    "render_runtime": "ffmpeg",
    "cuts": [
        {
            "id": "s1",
            "source": "assets/video/s1-take1.mp4",
            "in_seconds": 0,
            "out_seconds": 7.0,
        }
    ],
}


def test_fps_is_optional_and_accepted():
    doc = copy.deepcopy(SAMPLE)
    doc["fps"] = 24
    jsonschema.validate(doc, SCHEMA)


def test_document_without_fps_remains_valid():
    jsonschema.validate(copy.deepcopy(SAMPLE), SCHEMA)


@pytest.mark.parametrize("fps", [0, 121])
def test_fps_outside_supported_range_is_rejected(fps):
    doc = copy.deepcopy(SAMPLE)
    doc["fps"] = fps
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)
