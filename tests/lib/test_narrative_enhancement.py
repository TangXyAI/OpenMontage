from pathlib import Path

import pytest

from lib.checkpoint import read_checkpoint, write_checkpoint
from lib.narrative_assets import NarrativeAssets
from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose


def _catalog(tmp_path: Path) -> NarrativeAssets:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    for name in ("a.mp4", "b.mp4"):
        (root / name).write_bytes(b"video")
    catalog = NarrativeAssets(root)
    catalog.add_take("s1", "take1", "a.mp4", 7.0)
    catalog.add_take("s1", "take2", "b.mp4", 7.0)
    catalog.select_take("s1", "take1")
    return catalog


def _enhancement(path: str = "assets/video/enhanced/s1-take1-upscale.mp4") -> dict:
    return {
        "operation": "video_upscale",
        "model": "SeedVR2 3B FP8",
        "source_path": "a.mp4",
        "parameters": {"resolution": 1080},
        "workflow_hash_sha256": "abc",
    }


def test_apply_enhancement_requires_selected_take(tmp_path):
    catalog = _catalog(tmp_path)
    enhanced = tmp_path / "project" / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    with pytest.raises(ValueError, match="selected"):
        catalog.apply_enhancement("s1", "take2", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())


def test_apply_enhancement_keeps_first_original_path(tmp_path):
    catalog = _catalog(tmp_path)
    enhanced = tmp_path / "project" / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    first = catalog.data["shots"]["s1"]["takes"]["take1"]["metadata"]["original_path"]
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    assert catalog.data["shots"]["s1"]["takes"]["take1"]["metadata"]["original_path"] == first
    assert first == "a.mp4"


def test_asset_manifest_exposes_enhancement(tmp_path):
    catalog = _catalog(tmp_path)
    enhanced = tmp_path / "project" / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    take = next(item for item in catalog.asset_manifest()["assets"] if item["type"] == "video")
    assert take["enhancement"]["operation"] == "video_upscale"


def test_guarded_compose_accepts_enhanced_selection(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    root = tmp_path / "project"
    enhanced = root / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s1"], "ffmpeg")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: ToolResult(success=True))
    result = tool.execute({
        "operation": "render", "project_dir": str(root),
        "edit_decisions": edit, "asset_manifest": manifest,
        "output_path": str(root / "out.mp4"),
    })
    assert result.success, result.error


def test_guarded_compose_rejects_stale_path_after_enhancement(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    root = tmp_path / "project"
    enhanced = root / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s1"], "ffmpeg")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: ToolResult(success=True))
    result = tool.execute({
        "operation": "render", "project_dir": str(root),
        "edit_decisions": edit, "asset_manifest": manifest,
        "output_path": str(root / "out.mp4"),
    })
    assert not result.success
    assert "does not match narrative selection" in result.error
