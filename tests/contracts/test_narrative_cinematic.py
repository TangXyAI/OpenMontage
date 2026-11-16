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
