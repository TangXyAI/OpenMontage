from pathlib import Path

from lib.pipeline_loader import load_pipeline


def test_narrative_mode_lists_local_skills_first():
    manifest = load_pipeline("cinematic")
    modes = {mode["name"]: mode for mode in manifest["production_modes"]}
    skills = modes["narrative_generated"]["agent_skills"]
    assert skills[:2] == ["hyperflow-h3", "minimax-h3"]
    assert {"cinedance", "acting-system", "lira-image-prompts"} <= set(skills)


def test_assets_has_asset_and_model_gates():
    manifest = load_pipeline("cinematic")
    assets = next(stage for stage in manifest["stages"] if stage["name"] == "assets")
    sub = {stage["name"]: stage for stage in assets["sub_stages"]}
    assert sub["asset_sheets"]["human_approval_default"] is True
    assert sub["model_selection"]["human_approval_default"] is True


def test_required_skills_include_the_two_norms():
    manifest = load_pipeline("cinematic")
    assert {"creative/narrative-consistency", "creative/video-model-selection"} <= set(manifest["required_skills"])


ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "skills" / "pipelines" / "cinematic"


def test_proposal_presents_model_menu_and_logs_choice():
    text = (PIPELINE / "proposal-director.md").read_text(encoding="utf-8").lower()
    for phrase in ("video model shortlist", "local first", "provider_selection", "video model and route"):
        assert phrase in text


def test_asset_director_enforces_assets_then_model_then_takes():
    text = (PIPELINE / "asset-director.md").read_text(encoding="utf-8").lower()
    for phrase in ("asset sheets", "stress test", "360", "video character card", "model and route", "take budget"):
        assert phrase in text


def test_scene_director_names_required_assets_and_location_map():
    text = (PIPELINE / "scene-director.md").read_text(encoding="utf-8").lower()
    assert "required_assets" in text
    assert "location_map" in text


def test_edit_and_compose_cover_post_work():
    for name in ("edit-director.md", "compose-director.md"):
        text = (PIPELINE / name).read_text(encoding="utf-8").lower()
        for phrase in ("cleanup", "color", "sound"):
            assert phrase in text
