from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
