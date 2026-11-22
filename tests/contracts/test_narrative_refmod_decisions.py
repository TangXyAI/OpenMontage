import json
from pathlib import Path

import jsonschema

from lib.video_model_selection import record_reference_conditioning_selection


ROOT = Path(__file__).resolve().parents[2]
OPTIONS = [
    {
        "option_id": "project_refmod",
        "label": "Project RefMods",
        "score": 1.0,
        "reason": "Reuse approved project assets for local H3 shots.",
    },
    {
        "option_id": "native_ref2va",
        "label": "Native Ref2VA",
        "score": 0.7,
        "reason": "Use ordinary image references in local H3 Ref2VA.",
    },
]


def test_record_reference_conditioning_selection_appends_latest_mode(tmp_path):
    path = tmp_path / "decision_log.json"

    first = record_reference_conditioning_selection(
        path,
        "film",
        "assets",
        "project_refmod",
        OPTIONS,
        "Default to approved reusable assets for local H3.",
    )
    decision = record_reference_conditioning_selection(
        path,
        "film",
        "assets",
        "native_ref2va",
        OPTIONS,
        "The user chose native H3 references for this shot.",
    )

    log = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas/artifacts/decision_log.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(log, schema)

    assert decision["decision_id"] != first["decision_id"]
    assert decision["category"] == "reference_conditioning_selection"
    assert decision["subject"] == "MiniMax H3 reusable-asset conditioning"
    assert decision["selected"] == "native_ref2va"
    assert decision["user_approved"] is True
    assert len(log["decisions"]) == 2
    superseded = next(
        option
        for option in decision["options_considered"]
        if option["option_id"] == "project_refmod"
    )
    assert "changed" in superseded["rejected_because"].lower()


def test_reference_conditioning_requires_an_considered_option(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="options_considered"):
        record_reference_conditioning_selection(
            tmp_path / "decision_log.json",
            "film",
            "assets",
            "project_refmod",
            [OPTIONS[1]],
            "No matching option was supplied.",
        )
