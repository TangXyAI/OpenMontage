from pathlib import Path

import yaml  # PyYAML is already a project dependency

ROOT = Path(__file__).resolve().parents[2]

MANIFEST = ROOT / "pipeline_defs" / "cinematic.yaml"


def test_layer_three_skill_exists_and_covers_both_routes():
    path = ROOT / ".agents" / "skills" / "video-enhancement" / "SKILL.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "FaceRefine" in text and "SeedVR2" in text
    assert "frame_rate" in text and "SSIM" in text


def test_layer_two_skill_links_to_layer_three():
    path = ROOT / "skills" / "creative" / "video-enhancement.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert ".agents/skills/video-enhancement" in text
    assert "largest face" in text.lower() or "最大" in text


def test_cinematic_assets_has_enhancement_substage():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assets = next(stage for stage in manifest["stages"] if stage["name"] == "assets")
    names = [sub["name"] for sub in assets["sub_stages"]]
    assert "enhancement_selection" in names
    assert "comfyui_enhance" in assets["tools_available"]
    substage = next(sub for sub in assets["sub_stages"] if sub["name"] == "enhancement_selection")
    assert substage["human_approval_default"] is True
    assert "comfyui_enhance" in substage["tools_available"]


def test_asset_director_wires_the_gate():
    text = (ROOT / "skills" / "pipelines" / "cinematic" / "asset-director.md").read_text(encoding="utf-8")
    assert "video-enhancement.md" in text
    assert "enhancement_selection" in text
    assert "apply_enhancement" in text
    assert "require_selected_route" in text


def test_edit_director_raises_compose_target():
    text = (ROOT / "skills" / "pipelines" / "cinematic" / "edit-director.md").read_text(encoding="utf-8")
    assert "compose_target" in text
    assert "seedvr2_upscale" in text


def test_compose_director_forbids_re_enhancement():
    text = (ROOT / "skills" / "pipelines" / "cinematic" / "compose-director.md").read_text(encoding="utf-8")
    assert "comfyui_enhance" in text
    assert "silently" in text.lower() or "静默" in text
