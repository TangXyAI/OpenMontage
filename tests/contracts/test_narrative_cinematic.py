from pathlib import Path

import pytest

from lib.checkpoint import CheckpointValidationError, init_project, read_checkpoint, write_checkpoint
from lib.pipeline_loader import load_pipeline
from tests.contracts.test_phase0_contracts import sample_artifact


def test_existing_script_and_scene_plan_are_reused(tmp_path):
    init_project("film", title="Film", pipeline_type="cinematic", pipeline_dir=tmp_path)
    script = sample_artifact("script")
    scene = sample_artifact("scene_plan")
    script["sections"][0]["text"] = "Existing dialogue"
    scene["scenes"][0]["id"] = "shot-existing"
    with pytest.raises(CheckpointValidationError):
        write_checkpoint(tmp_path, "film", "script", "completed", {"script": script}, pipeline_type="cinematic", human_approved=True)
    write_checkpoint(tmp_path, "film", "research", "completed", {"research_brief": sample_artifact("research_brief")}, pipeline_type="cinematic")
    proposal = sample_artifact("proposal_packet")
    proposal["production_plan"]["pipeline"] = "cinematic"
    write_checkpoint(tmp_path, "film", "proposal", "completed", {"proposal_packet": proposal}, pipeline_type="cinematic", human_approved=True)
    with pytest.raises(CheckpointValidationError):
        write_checkpoint(tmp_path, "film", "script", "completed", {"script": script}, pipeline_type="cinematic")
    write_checkpoint(tmp_path, "film", "script", "completed", {"script": script}, pipeline_type="cinematic", human_approved=True)
    write_checkpoint(tmp_path, "film", "scene_plan", "completed", {"scene_plan": scene}, pipeline_type="cinematic", human_approved=True)
    assert read_checkpoint(tmp_path, "film", "script")["artifacts"]["script"]["sections"][0]["text"] == "Existing dialogue"
    assert read_checkpoint(tmp_path, "film", "scene_plan")["artifacts"]["scene_plan"]["scenes"][0]["id"] == "shot-existing"


def test_narrative_and_source_led_modes_keep_distinct_asset_rules():
    manifest = load_pipeline("cinematic")
    modes = {mode["name"]: mode for mode in manifest["production_modes"]}
    assert {"source_led", "narrative_generated"} <= set(modes)
    assert {"image_selector", "video_selector"} <= set(modes["narrative_generated"]["required_tools"])
    stages = {stage["name"]: stage for stage in manifest["stages"]}
    assert all(stages[name]["human_approval_default"] for name in ("proposal", "script", "scene_plan", "assets"))


def test_narrative_continuity_version_and_existing_project_opt_in_are_documented():
    text = (Path(__file__).resolve().parents[2] / "skills/pipelines/cinematic/proposal-director.md").read_text(encoding="utf-8")
    assert 'continuity_contract_version: "1.0"' in text
    assert "approval_policy" in text
    assert "Scene continuity contract version" in text


def test_continuity_checks_bracket_scene_and_shot_generation():
    root = Path(__file__).resolve().parents[2]
    scene_text = (root / "skills/pipelines/cinematic/scene-director.md").read_text(encoding="utf-8")
    asset_text = (root / "skills/pipelines/cinematic/asset-director.md").read_text(encoding="utf-8")
    asset_pipeline = asset_text[asset_text.index("## Narrative Asset Pipeline"):]
    assert "validate_scene_plan_continuity" in scene_text
    assert "generate the location plate" in scene_text
    assert scene_text.index("validate_scene_plan_continuity") < scene_text.index("generate the location plate")
    assert "After the `asset_sheets` approval" in asset_pipeline
    assert "validate_shot_continuity" in asset_pipeline
    assert "Batch takes" in asset_pipeline
    assert asset_pipeline.index("After the `asset_sheets` approval") < asset_pipeline.index("validate_shot_continuity") < asset_pipeline.index("Batch takes")


def test_cinematic_manifest_requires_review_evidence_only_for_strict_narrative_mode():
    manifest = load_pipeline("cinematic")
    assets = next(stage for stage in manifest["stages"] if stage["name"] == "assets")
    assert any("strict narrative" in item.lower() and "continuity review" in item.lower() for item in assets["review_focus"])
