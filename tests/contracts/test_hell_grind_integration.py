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


def test_refmod_stage_uses_server_info_and_shared_workspace_contract():
    manifest = load_pipeline("cinematic")
    assets = next(stage for stage in manifest["stages"] if stage["name"] == "assets")
    assert "comfyui_refmod" in assets["tools_available"]

    asset_text = (PIPELINE / "asset-director.md").read_text(encoding="utf-8")
    for phrase in (
        "server_info",
        "workspace.path",
        "server_url",
        "same descriptors, selected `server_url`",
        "stale RefMod",
    ):
        assert phrase in asset_text


def test_h3_skill_and_narrative_guide_preserve_refmod_route_boundaries():
    root = Path(__file__).resolve().parents[2]
    h3_skill = (root / ".agents/skills/minimax-h3/SKILL.md").read_text(
        encoding="utf-8"
    )
    hyperflow_skill = (root / ".agents/skills/hyperflow-h3/SKILL.md").read_text(
        encoding="utf-8"
    )
    narrative_guide = (root / "docs/narrative-production.md").read_text(
        encoding="utf-8"
    )

    assert "Project-scoped RefMods" in h3_skill
    assert "first_last_frame_to_video" in h3_skill
    assert "MiniMaxH3RefModTextEncode" in hyperflow_skill
    assert "does not accept separate native video references" in hyperflow_skill
    assert "reference_conditioning_selection" in narrative_guide
    assert "stale source or Mod blocks" in narrative_guide
