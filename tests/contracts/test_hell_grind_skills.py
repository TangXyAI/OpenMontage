from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = {
    # The archive's CINEDANCE skill uses "SINGLE CONTINUOUS TAKE" (it never
    # contains the literal "ONE-TAKE"), and the copy must stay byte-for-byte.
    "cinedance": "SINGLE CONTINUOUS TAKE",
    "acting-system": "acting is BEHAVIOR",
    "lira-image-prompts": "Soul Cinema",
}


@pytest.mark.parametrize("slug,phrase", SKILLS.items())
def test_skill_exists_with_frontmatter(slug, phrase):
    path = ROOT / ".agents" / "skills" / slug / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    frontmatter, body = text.split("---", 2)[1], text.split("---", 2)[2]
    assert f"name: {slug}" in frontmatter
    assert len(body) > 5000
    assert phrase.lower() in body.lower()


def test_hyperflow_skill_records_routes_and_license():
    text = (ROOT / ".agents" / "skills" / "hyperflow-h3" / "SKILL.md").read_text(encoding="utf-8")
    assert "HyperFlowINT8Loader" in text
    assert "MiniMax H3 Community License" in text
    assert "ModelScope" in text
