from pathlib import Path

from lib.checkpoint import write_checkpoint, read_checkpoint
from lib.narrative_assets import NarrativeAssets
from schemas.artifacts import validate_artifact
from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose
from tests.contracts.test_narrative_comfy_http import comfy_server


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


def test_direct_compose_rejects_stale_narrative_selection(tmp_path, monkeypatch):
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    manifest, edit = catalog.asset_manifest(), catalog.edit_decisions(["shot-1"], "ffmpeg")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    catalog.select_take("shot-1", "b")
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_compose", lambda inputs: ToolResult(success=True))
    result = tool.execute({"operation": "compose", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(root / "out.mp4")})
    assert not result.success and "selection" in result.error.lower()


def test_strict_narrative_selection_without_current_review_blocks_compose(tmp_path, monkeypatch):
    from tests.contracts.test_phase0_contracts import sample_artifact

    root = tmp_path / "project"
    catalog = setup_catalog(root)
    catalog.register_shot("shot-1", "scene-1", continuity_contract_version="1.0")
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["shot-1"], "ffmpeg")

    write_checkpoint(tmp_path, "project", "research", "completed", {"research_brief": sample_artifact("research_brief")}, pipeline_type="cinematic")
    proposal = sample_artifact("proposal_packet")
    proposal["production_plan"]["pipeline"] = "cinematic"
    proposal.setdefault("metadata", {})["continuity_contract_version"] = "1.0"
    write_checkpoint(tmp_path, "project", "proposal", "completed", {"proposal_packet": proposal}, pipeline_type="cinematic", human_approved=True)
    script = sample_artifact("script")
    write_checkpoint(tmp_path, "project", "script", "completed", {"script": script}, pipeline_type="cinematic", human_approved=True)
    scene_plan = sample_artifact("scene_plan")
    write_checkpoint(tmp_path, "project", "scene_plan", "completed", {"scene_plan": scene_plan}, pipeline_type="cinematic", human_approved=True)
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, pipeline_type="cinematic", human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit}, pipeline_type="cinematic")

    tool = VideoCompose()
    monkeypatch.setattr(tool, "_compose", lambda inputs: ToolResult(success=True))
    result = tool.execute({
        "operation": "compose", "project_dir": str(root),
        "edit_decisions": edit, "asset_manifest": manifest,
        "output_path": str(root / "out.mp4"),
    })
    assert not result.success
    assert "continuity review" in result.error.lower()


def test_renamed_editorial_cut_cannot_use_unselected_take(tmp_path, monkeypatch):
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    manifest, edit = catalog.asset_manifest(), catalog.edit_decisions(["shot-1"], "ffmpeg")
    edit["cuts"][0].update({"id": "cut-1", "source": str(root / "b.mp4")})
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_compose", lambda inputs: ToolResult(success=True))
    result = tool.execute({"operation": "compose", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(root / "out.mp4")})
    assert not result.success


def test_relative_selected_cut_resolves_to_project_not_cwd(tmp_path, monkeypatch):
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    (tmp_path / "a.mp4").write_bytes(b"other")
    manifest, edit = catalog.asset_manifest(), catalog.edit_decisions(["shot-1"], "ffmpeg")
    edit["cuts"][0]["source"] = "a.mp4"
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    tool = VideoCompose()
    captured = []
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: captured.extend(kwargs["resolved_cuts"]) or ToolResult(success=True))
    monkeypatch.chdir(tmp_path)
    result = tool.execute({"operation": "render", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(root / "out.mp4")})
    assert result.success, result.error
    assert Path(captured[0]["source"]) == root / "a.mp4"


def test_relative_selected_cut_renders_project_media_not_cwd(tmp_path, monkeypatch):
    import subprocess
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    for color, path in (("blue", root / "a.mp4"), ("red", tmp_path / "a.mp4")):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=64x64:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    manifest, edit = catalog.asset_manifest(), catalog.edit_decisions(["shot-1"], "ffmpeg")
    edit["cuts"][0]["source"] = "a.mp4"
    edit["renderer_family"] = "cinematic-trailer"
    edit["metadata"]["compose_target"] = {"width": 64, "height": 64}
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    monkeypatch.chdir(tmp_path)
    output = root / "out.mp4"
    result = VideoCompose().execute({"operation": "render", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(output)})
    assert result.success, result.error
    frame = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-ss", "0.3", "-i", str(output), "-frames:v", "1", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    assert frame[2] > frame[0]


def test_cache_cannot_bypass_selection_approval_after_reselection(tmp_path, monkeypatch):
    from lib.asset_cache import reset_default_asset_cache
    root = tmp_path / "project"
    catalog = setup_catalog(root)
    manifest, edit = catalog.asset_manifest(), catalog.edit_decisions(["shot-1"], "ffmpeg")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    monkeypatch.setenv("OPENMONTAGE_ASSET_CACHE", "1")
    monkeypatch.setenv("OPENMONTAGE_ASSET_CACHE_DIR", str(tmp_path / "cache"))
    reset_default_asset_cache()
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    def render(**kwargs):
        output = kwargs["output_path"]
        output.write_bytes(b"render")
        return ToolResult(success=True, artifacts=[str(output)])
    monkeypatch.setattr(tool, "_render_via_ffmpeg", render)
    inputs = {"operation": "render", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(root / "out.mp4")}
    assert tool.execute(inputs).success
    catalog.select_take("shot-1", "b")
    result = tool.execute(inputs)
    assert not result.success
    reset_default_asset_cache()


def test_two_shot_pipeline_with_fake_comfyui(tmp_path, monkeypatch, comfy_server):
    import json
    import subprocess
    from lib.checkpoint import init_project
    from tests.contracts.test_phase0_contracts import sample_artifact
    from tools.video.comfyui_video import ComfyUIVideo

    root = init_project("film", title="Film", pipeline_type="cinematic", pipeline_dir=tmp_path)
    write_checkpoint(tmp_path, "film", "research", "completed", {"research_brief": sample_artifact("research_brief")}, pipeline_type="cinematic")
    proposal = sample_artifact("proposal_packet")
    proposal["production_plan"].update({"pipeline": "cinematic", "render_runtime": "ffmpeg", "renderer_family": "cinematic-trailer"})
    write_checkpoint(tmp_path, "film", "proposal", "completed", {"proposal_packet": proposal}, pipeline_type="cinematic", human_approved=True)
    script = sample_artifact("script")
    write_checkpoint(tmp_path, "film", "script", "completed", {"script": script}, pipeline_type="cinematic", human_approved=True)
    scene = sample_artifact("scene_plan")
    scene["scenes"] = [{"id": "shot-1", "type": "generated", "description": "one", "start_seconds": 0, "end_seconds": 1}, {"id": "shot-2", "type": "generated", "description": "two", "start_seconds": 1, "end_seconds": 2}]
    write_checkpoint(tmp_path, "film", "scene_plan", "completed", {"scene_plan": scene}, pipeline_type="cinematic", human_approved=True)

    for color in ("red", "blue"):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=64x64:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / f"{color}.mp4")], check=True)
    url, state = comfy_server
    state["media"] = {"p1.mp4": (tmp_path / "red.mp4").read_bytes(), "p2.mp4": (tmp_path / "blue.mp4").read_bytes(), "p3.mp4": (tmp_path / "red.mp4").read_bytes(), "p4.mp4": (tmp_path / "blue.mp4").read_bytes()}
    tool = ComfyUIVideo()
    tool._client.server_url = url
    monkeypatch.setattr(tool._client, "_wait", lambda prompt_id, **kwargs: tool._client.poll(prompt_id, timeout=1, interval=0))
    catalog = NarrativeAssets(root)
    for asset in ("hero", "place"):
        (root / "assets" / "images" / f"{asset}.png").write_bytes(b"png")
        catalog.put_asset(asset, "character" if asset == "hero" else "location", asset, f"assets/images/{asset}.png")
    graph = {"1": {"inputs": {"image": "old"}}, "2": {"inputs": {"image": "old"}}, "9": {"inputs": {}}}
    for shot in ("shot-1", "shot-2"):
        catalog.link_assets(shot, ["hero", "place"])
        for take in ("take-1", "take-2"):
            output = root / "assets" / "video" / f"{shot}-{take}.mp4"
            result = tool.execute({"prompt": shot, "model_family": "minimax_h3_local", "workflow_json": json.dumps(graph), "output_node": "9", "output_path": str(output), "reference_images": {"hero": str(root / "assets/images/hero.png"), "place": str(root / "assets/images/place.png")}, "workflow_bindings": {"reference_images.hero": [{"node": "1", "input": "image"}], "reference_images.place": [{"node": "2", "input": "image"}]}})
            assert result.success, result.error
            catalog.add_take(shot, take, str(output), 1, {"seed": result.seed, "workflow_provenance": result.data["workflow_provenance"]})
    catalog = NarrativeAssets(root)
    catalog.select_take("shot-1", "take-1")
    catalog.select_take("shot-2", "take-2")
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["shot-1", "shot-2"], "ffmpeg")
    edit["renderer_family"] = "cinematic-trailer"
    edit["metadata"]["compose_target"] = {"width": 64, "height": 64}
    write_checkpoint(tmp_path, "film", "assets", "completed", {"asset_manifest": manifest}, pipeline_type="cinematic", human_approved=True)
    write_checkpoint(tmp_path, "film", "edit", "completed", {"edit_decisions": edit}, pipeline_type="cinematic")
    output = root / "renders" / "film.mp4"
    result = VideoCompose().execute({"operation": "render", "project_dir": str(root), "edit_decisions": edit, "asset_manifest": manifest, "output_path": str(output)})
    assert result.success, result.error
    assert output.is_file() and len(state["prompts"]) == 4 and state["uploads"] == 8
    assert len(NarrativeAssets(root).data["shots"]["shot-1"]["takes"]) == 2
    for timestamp, expected in (("0.3", "red"), ("1.3", "blue")):
        frame = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-ss", timestamp, "-i", str(output), "-frames:v", "1", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        assert (frame[0] > frame[2]) == (expected == "red")
