from pathlib import Path

import pytest

from lib.narrative_assets import validate_character_sheet


def test_character_sheet_requires_three_existing_images(tmp_path):
    paths = []
    for name in ("face.png", "front.png", "back.png"):
        path = tmp_path / name
        path.write_bytes(b"image")
        paths.append(path)
    validate_character_sheet("Hero, wet, white hair", paths)
    with pytest.raises(ValueError, match="exactly three"):
        validate_character_sheet("Hero", paths[:2])
    with pytest.raises(ValueError, match="missing"):
        validate_character_sheet("Hero", [*paths[:2], tmp_path / "missing.png"])
    with pytest.raises(ValueError, match="descriptor"):
        validate_character_sheet("", paths)
