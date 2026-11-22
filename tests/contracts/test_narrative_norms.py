from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {
    "narrative-consistency.md": [
        "## Asset order", "## Continuity contract", "## Character sheets", "## Scene lock",
        "## Stress test", "## Take budget",
    ],
    "video-model-selection.md": [
        "## Local first", "## Selection gate", "## Menu",
        "## Draft and final", "## No silent fallback",
    ],
}


def test_norms_have_required_sections():
    for name, headings in REQUIRED.items():
        text = (ROOT / "skills" / "creative" / name).read_text(encoding="utf-8")
        for heading in headings:
            assert heading in text, f"{name} missing {heading}"


def test_video_prompting_links_to_norms():
    text = (ROOT / "skills" / "creative" / "video-gen-prompting.md").read_text(encoding="utf-8")
    assert "narrative-consistency" in text
    assert "cinedance" in text
