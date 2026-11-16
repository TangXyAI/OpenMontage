import json
from pathlib import Path

import pytest

from tools.graphics.comfyui_image import ComfyUIImage
from tools.video.comfyui_video import ComfyUIVideo


@pytest.mark.parametrize("tool_class", [ComfyUIImage, ComfyUIVideo])
def test_custom_workflow_injects_prompt_seed_and_uploaded_reference(tool_class, tmp_path):
    tool = tool_class()
    tool._client.is_available = lambda: True
    image = tmp_path / "frame.png"
    image.write_bytes(b"image")
    tool._client.upload_image = lambda path, name: "uploaded.png"
    received = {}

    def generate(workflow, output_node, dest, **kwargs):
        received.update(workflow)
        Path(dest).write_bytes(b"result")
        return [Path(dest)]

    tool._client.generate = generate
    result = tool.execute({
        "prompt": "a new shot", "seed": 0,
        "workflow_json": json.dumps({"1": {"inputs": {"text": "old"}}, "2": {"inputs": {"seed": 9}}, "3": {"inputs": {"image": "old.png"}}}),
        "output_node": "3", "output_path": str(tmp_path / "out.mp4"),
        "reference_image_path": str(image),
        "workflow_bindings": {"prompt": [{"node": "1", "input": "text"}], "seed": [{"node": "2", "input": "seed"}], "reference_image_path": [{"node": "3", "input": "image"}]},
    })
    assert result.success, result.error
    assert received["1"]["inputs"]["text"] == "a new shot"
    assert received["2"]["inputs"]["seed"] == 0
    assert received["3"]["inputs"]["image"] == "uploaded.png"


def test_narrative_library_preserves_versions_and_builds_cuts(tmp_path):
    from lib.narrative_assets import NarrativeAssets

    library = NarrativeAssets(tmp_path)
    (tmp_path / "hero.png").write_bytes(b"image")
    (tmp_path / "take1.mp4").write_bytes(b"video1")
    (tmp_path / "take2.mp4").write_bytes(b"video2")
    library.put_asset("hero", "character", "Hero", "hero.png", state="wet")
    library.add_take("shot-1", "take1", "take1.mp4", 3.0, {"seed": 1})
    library.add_take("shot-1", "take2", "take2.mp4", 4.0, {"seed": 2})
    library.select_take("shot-1", "take2")
    reloaded = NarrativeAssets(tmp_path)
    assert reloaded.data["assets"]["hero"]["state"] == "wet"
    assert len(reloaded.data["shots"]["shot-1"]["takes"]) == 2
    edit = reloaded.edit_decisions(["shot-1"], "ffmpeg")
    import jsonschema
    schema = json.loads((Path(__file__).parents[2] / "schemas/artifacts/edit_decisions.schema.json").read_text())
    jsonschema.validate(edit, schema)
    assert edit["cuts"][0]["source"] == str(tmp_path / "take2.mp4")
    assert edit["cuts"][0]["out_seconds"] == 4.0


def test_assets_can_be_linked_to_shots_and_exported_to_manifest(tmp_path):
    from lib.narrative_assets import NarrativeAssets
    import jsonschema

    for name in ("hero.png", "take.mp4"):
        (tmp_path / name).write_bytes(b"media")
    library = NarrativeAssets(tmp_path)
    library.put_asset("hero", "character", "Hero", "hero.png")
    library.link_assets("shot-1", ["hero"])
    library.add_take("shot-1", "take1", "take.mp4", 3, {"seed": 5})
    library.select_take("shot-1", "take1")
    manifest = NarrativeAssets(tmp_path).asset_manifest()
    schema = json.loads((Path(__file__).parents[2] / "schemas/artifacts/asset_manifest.schema.json").read_text())
    jsonschema.validate(manifest, schema)
    assert {a["path"] for a in manifest["assets"]} == {"hero.png", "take.mp4"}
    assert all(a["scene_id"] == "shot-1" for a in manifest["assets"])
    assert any(a["seed"] == 5 for a in manifest["assets"] if a["type"] == "video")


def test_binding_rejects_graph_connections_before_submitting():
    from tools._comfyui.client import ComfyUIClient, ComfyUIError

    with pytest.raises(ComfyUIError, match="connection"):
        ComfyUIClient().bind_workflow({"1": {"inputs": {"text": ["2", 0]}}}, {"prompt": [{"node": "1", "input": "text"}]}, {"prompt": "x"})


def test_multiple_reference_assets_bind_to_separate_nodes(tmp_path):
    from tools._comfyui.client import ComfyUIClient

    hero, place = tmp_path / "hero.png", tmp_path / "place.png"
    hero.write_bytes(b"h")
    place.write_bytes(b"p")
    client = ComfyUIClient()
    client.upload_image = lambda path, name: "remote-" + path.name
    workflow = {"1": {"inputs": {"image": "old"}}, "2": {"inputs": {"image": "old"}}}
    result = client.bind_workflow(workflow, {
        "reference_images.hero": [{"node": "1", "input": "image"}],
        "reference_images.place": [{"node": "2", "input": "image"}],
    }, {"reference_images": {"hero": str(hero), "place": str(place)}})
    assert result["1"]["inputs"]["image"] == "remote-hero.png"
    assert result["2"]["inputs"]["image"] == "remote-place.png"


def test_catalog_round_trip_multiple_scenes_and_versions(tmp_path):
    from lib.narrative_assets import NarrativeAssets
    for name in ("dry.png", "wet.png", "a.mp4", "b.mp4", "c.mp4", "d.mp4"):
        (tmp_path / name).write_bytes(b"media")
    c = NarrativeAssets(tmp_path)
    c.put_asset("dry", "character", "Hero", "dry.png", state="dry")
    c.put_asset("wet", "character", "Hero", "wet.png", state="wet")
    c.link_assets("s1", ["dry"])
    c.link_assets("s2", ["wet"])
    metadata = {"prompt": "rain", "seed": 0, "model": "H3", "workflow_hash": "abc", "change": "slower", "review": "good"}
    for shot, take, path in (("s1", "a", "a.mp4"), ("s1", "b", "b.mp4"), ("s2", "c", "c.mp4"), ("s2", "d", "d.mp4")):
        c.add_take(shot, take, path, 2, metadata)
    c.select_take("s1", "a")
    c.select_take("s2", "d")
    restored = NarrativeAssets(tmp_path)
    assert restored.data["shots"]["s2"]["takes"]["d"]["metadata"] == metadata
    assert restored.data["shots"]["s1"]["asset_ids"] == ["dry"]
    assert restored.data["shots"]["s2"]["selected"] == "d"
    assert len(restored.data["shots"]["s1"]["takes"]) == 2


def test_catalog_rejects_escape_symlink_and_duplicate_ids(tmp_path):
    from lib.narrative_assets import NarrativeAssets
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.png").write_bytes(b"x")
    (project / "link.png").symlink_to(tmp_path / "outside.png")
    (project / "image.png").write_bytes(b"x")
    c = NarrativeAssets(project)
    for path in ("../outside.png", "link.png"):
        with pytest.raises(ValueError):
            c.put_asset("bad", "character", "x", path)
    c.put_asset("c", "character", "x", "image.png")
    c.put_asset("b:c", "character", "x", "image.png")
    with pytest.raises(ValueError):
        c.put_asset("c", "character", "overwrite", "image.png")
    c.link_assets("a:b", ["c"])
    c.link_assets("a", ["b:c"])
    ids = [item["id"] for item in c.asset_manifest()["assets"]]
    assert len(set(ids)) == 2
    c.add_take("a", "t", "image.png", 1)
    with pytest.raises(ValueError):
        c.add_take("a", "t", "image.png", 1)


def test_catalog_rejects_missing_file_and_unselected_shot(tmp_path):
    from lib.narrative_assets import NarrativeAssets
    c = NarrativeAssets(tmp_path)
    with pytest.raises(ValueError):
        c.add_take("s", "missing", "missing.mp4", 1)
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mp4").write_bytes(b"b")
    c.add_take("s", "a", "a.mp4", 1)
    c.add_take("s", "b", "b.mp4", 1)
    with pytest.raises(ValueError):
        c.edit_decisions(["s"], "ffmpeg")
    c.select_take("s", "a")
    c.select_take("s", "b")
    assert set(c.data["shots"]["s"]["takes"]) == {"a", "b"}
    (tmp_path / "b.mp4").unlink()
    with pytest.raises(ValueError):
        c.asset_manifest()


def test_catalog_detects_stale_writers(tmp_path):
    from lib.narrative_assets import NarrativeAssets
    (tmp_path / "a.png").write_bytes(b"x")
    first, second = NarrativeAssets(tmp_path), NarrativeAssets(tmp_path)
    first.put_asset("a", "character", "A", "a.png")
    with pytest.raises(RuntimeError, match="changed"):
        second.put_asset("b", "character", "B", "a.png")
    assert set(NarrativeAssets(tmp_path).data["assets"]) == {"a"}


def test_catalog_rejects_reusing_a_take_file_for_another_version(tmp_path):
    from lib.narrative_assets import NarrativeAssets
    (tmp_path / "clip.mp4").write_bytes(b"video")
    catalog = NarrativeAssets(tmp_path)
    catalog.add_take("shot-1", "a", "clip.mp4", 1)
    with pytest.raises(ValueError, match="already"):
        catalog.add_take("shot-1", "b", "clip.mp4", 1)
    assert set(catalog.data["shots"]["shot-1"]["takes"]) == {"a"}


@pytest.mark.parametrize("tool_class", [ComfyUIImage, ComfyUIVideo])
def test_custom_workflow_reports_requested_inputs_as_unbound(tool_class, tmp_path):
    tool = tool_class()
    tool._client.is_available = lambda: True
    tool._client.generate = lambda workflow, output_node, dest, **kwargs: [Path(dest)]
    result = tool.execute({"prompt": "requested", "seed": 5, "workflow_json": json.dumps({"9": {"inputs": {}}}), "output_node": "9", "output_path": str(tmp_path / "out.mp4")})
    assert result.success, result.error
    assert result.data["workflow_provenance"]["input_bindings"] == []
    assert result.data["workflow_provenance"]["requested_parameters_applied"] is False
