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
