from pathlib import Path

from lib.checkpoint import write_checkpoint, read_checkpoint
from lib.narrative_assets import NarrativeAssets
from schemas.artifacts import validate_artifact
from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose


def setup_catalog(root):
    root.mkdir(parents=True)
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (root / name).write_bytes(b"video")
    catalog = NarrativeAssets(root)
    catalog.add_take("shot-1", "a", "a.mp4", 1)
    catalog.add_take("shot-1", "b", "b.mp4", 1)
    catalog.add_take("shot-2", "c", "c.mp4", 1)
    catalog.select_take("shot-1", "a")
    catalog.select_take("shot-2", "c")
    return catalog


def test_selected_takes_resolve_from_project_directory(tmp_path, monkeypatch):
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["shot-2", "shot-1"], "ffmpeg")
    validate_artifact("asset_manifest", manifest)
    validate_artifact("edit_decisions", edit)
    lookup = {item["scene_id"]: item["id"] for item in manifest["assets"] if item["type"] == "video"}
    for cut in edit["cuts"]:
        cut["source"] = lookup[cut["id"]]
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    tool = VideoCompose()
    captured = []
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: captured.extend(kwargs["resolved_cuts"]) or ToolResult(success=True))
    monkeypatch.chdir(tmp_path)
    result = tool.execute({"operation": "render", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(root / "out.mp4")})
    assert result.success, result.error
    assert [Path(c["source"]) for c in captured] == [root / "c.mp4", root / "a.mp4"]


def test_changing_selection_blocks_stale_edit_checkpoint(tmp_path, monkeypatch):
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["shot-1"], "ffmpeg")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    saved = read_checkpoint(tmp_path, "project", "edit")["artifacts"]["edit_decisions"]
    catalog.select_take("shot-1", "b")
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: ToolResult(success=True))
    result = tool.execute({"operation": "render", "project_dir": str(root), "edit_decisions": saved, "asset_manifest": manifest, "output_path": str(root / "out.mp4")})
    assert not result.success and "selection" in result.error.lower()
    fresh_manifest, fresh_edit = catalog.asset_manifest(), catalog.edit_decisions(["shot-1"], "ffmpeg")
    result = tool.execute({"operation": "render", "project_dir": str(root), "edit_decisions": fresh_edit, "asset_manifest": fresh_manifest, "output_path": str(root / "out.mp4")})
    assert not result.success
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": fresh_manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": fresh_edit})
    result = tool.execute({"operation": "render", "project_dir": str(root), "edit_decisions": fresh_edit, "asset_manifest": fresh_manifest, "output_path": str(root / "out.mp4")})
    assert result.success, result.error
    assert set(catalog.data["shots"]["shot-1"]["takes"]) == {"a", "b"}


def test_selected_snapshot_cannot_render_an_unselected_take(tmp_path, monkeypatch):
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    manifest, edit = catalog.asset_manifest(), catalog.edit_decisions(["shot-1"], "ffmpeg")
    edit["cuts"][0]["source"] = str(root / "b.mp4")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: ToolResult(success=True))
    result = tool.execute({"operation": "render", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(root / "out.mp4")})
    assert not result.success
