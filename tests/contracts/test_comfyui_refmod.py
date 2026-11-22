import json
from pathlib import Path
from tools.video.comfyui_refmod import ComfyUIRefMod


class FakeComfyUIClient:
    def __init__(self, workspace: Path, *, missing_node: str | None = None):
        self.workspace = workspace
        self.missing_node = missing_node
        self.server_url = "http://127.0.0.1:8290"
        self.workflow = None
        self.submission_count = 0
        self.available = True

    def is_available(self):
        return self.available

    def unavailable_reason(self):
        return "selected ComfyUI server is unavailable"

    def has_node(self, node_class: str) -> bool:
        return node_class != self.missing_node

    def check_models(self, required: list[str]):
        return list(required), []

    def check_node_inputs(self, _node_class, _required_inputs):
        return []

    def list_models(self):
        return {"vae": ["minimax_h3_video_vae_fp16.safetensors"]}

    def upload_image(self, local_path: Path, name: str):
        return f"input/{name}"

    def bind_workflow(self, workflow, bindings, values):
        bound = json.loads(json.dumps(workflow))
        for parameter, targets in bindings.items():
            value = values.get(parameter)
            if parameter == "reference_image_path":
                value = self.upload_image(Path(value), "approved-reference.png")
            for target in targets:
                bound[target["node"]]["inputs"][target["input"]] = value
        return bound

    def submit(self, workflow):
        self.workflow = workflow
        self.submission_count += 1
        return f"prompt-{self.submission_count}"

    def poll(self, prompt_id, *, timeout, interval):
        inputs = self.workflow["4"]["inputs"]
        model_path = self.workspace / "models" / "refmods" / inputs["subfolder"] / f"{inputs['name']}.safetensors"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"generated-refmod:" + inputs["name"].encode("utf-8"))
        details = json.dumps({"saved_paths": [str(model_path)]})
        return {"outputs": {"4": {"text": [details]}}}


def _catalog(project: Path) -> None:
    from lib.narrative_assets import NarrativeAssets

    image = project / "assets" / "images" / "hero.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"approved-character-sheet")
    catalog = NarrativeAssets(project)
    catalog.put_asset("hero", "character", "Courier in a dark coat", "assets/images/hero.png", entity_id="hero")


def test_refmod_tool_contract_and_project_asset_creation(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    tool = ComfyUIRefMod()
    assert tool.name == "comfyui_refmod"
    assert tool.capability == "asset_conditioning"
    result = tool.execute({
        "project_id": "film-a",
        "project_dir": str(project),
        "comfyui_workspace": str(workspace),
        "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero",
        "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    })

    assert result.success, result.error
    assert Path(result.data["project_path"]).as_posix().startswith("assets/refmods/")
    assert result.data["loader_name"].startswith("openmontage/film-a/")
    assert Path(project, result.data["project_path"]).is_file()
    assert Path(workspace, "models", "refmods", result.data["loader_name"] + ".safetensors").is_file()
    from lib.narrative_assets import NarrativeAssets
    manifest = NarrativeAssets(project).asset_manifest()
    assert manifest["metadata"]["refmod_assets"]["hero"]["status"] == "ready"


def test_static_project_assets_are_extracted_as_picture_refs(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    })

    assert result.success, result.error
    assert fake.workflow["4"]["inputs"]["image_refs"] == "separate"


def test_refmod_extraction_blocks_when_selected_node_lacks_a_workflow_socket(
    tmp_path, monkeypatch
):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    fake.check_node_inputs = lambda node, _required: (
        ["image_refs"] if node == "MiniMaxH3RefModExtract" else []
    )
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    })

    assert not result.success
    assert "MiniMaxH3RefModExtract" in result.error
    assert "image_refs" in result.error
    assert fake.submission_count == 0


def test_refmod_provenance_records_extension_version_and_video_vae(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module
    from lib.narrative_assets import NarrativeAssets

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    extension = workspace / "custom_nodes" / "ComfyUI-MiniMaxH3Mod" / "pyproject.toml"
    extension.parent.mkdir(parents=True)
    extension.write_text('[project]\nversion = "0.2.7"\n', encoding="utf-8")
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors", "concept_type": "identity",
    })

    assert result.success, result.error
    model_stack = NarrativeAssets(project).asset_manifest()["metadata"]["refmod_assets"]["hero"]["extractor"]["model_stack"]
    assert {"role": "refmod_extension", "name": "ComfyUI-MiniMaxH3Mod", "version": "0.2.7"} in model_stack
    assert {"role": "video_vae", "name": "minimax_h3_video_vae_fp16.safetensors"} in model_stack


def test_refmod_tool_reuses_identical_extraction(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)
    tool = ComfyUIRefMod()
    inputs = {
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    }

    first = tool.execute(inputs)
    second = tool.execute(inputs)

    assert first.success and second.success
    assert second.data["from_cache"] is True
    assert fake.submission_count == 1


def test_refmod_cache_hit_still_checks_the_selected_server(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)
    tool = ComfyUIRefMod()
    inputs = {
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    }
    first = tool.execute(inputs)
    assert first.success

    fake.available = False
    second = tool.execute(inputs)

    assert not second.success
    assert "selected ComfyUI server is unavailable" in second.error
    assert fake.submission_count == 1


def test_refmod_cache_hit_repairs_a_missing_or_changed_loader_copy(
    tmp_path, monkeypatch
):
    import hashlib
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)
    tool = ComfyUIRefMod()
    inputs = {
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    }
    first = tool.execute(inputs)
    loader_copy = workspace / "models" / "refmods" / f"{first.data['loader_name']}.safetensors"
    expected = project / first.data["project_path"]
    assert first.success and loader_copy.is_file()

    loader_copy.unlink()
    repaired_missing = tool.execute(inputs)
    loader_copy.write_bytes(b"tampered-loader-cache")
    repaired_changed = tool.execute(inputs)

    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert repaired_missing.success and repaired_missing.data["from_cache"] is True
    assert repaired_changed.success and repaired_changed.data["from_cache"] is True
    assert digest(loader_copy) == digest(expected)
    assert fake.submission_count == 1


def test_refmod_extraction_rejects_source_changed_while_polling(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module
    from lib.narrative_assets import NarrativeAssets

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    source = project / "assets" / "images" / "hero.png"
    fake = FakeComfyUIClient(workspace)
    original_poll = fake.poll

    def change_source_during_poll(*args, **kwargs):
        history = original_poll(*args, **kwargs)
        source.write_bytes(b"changed-after-upload")
        return history

    fake.poll = change_source_during_poll
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    })

    assert not result.success
    assert "source changed during extraction" in result.error.lower()
    assert "hero" not in NarrativeAssets(project).data.get("refmod_assets", {})


def test_refmod_tool_refuses_unindexed_loader_path_collision(tmp_path, monkeypatch):
    import hashlib
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    source_hash = hashlib.sha256((project / "assets/images/hero.png").read_bytes()).hexdigest()
    paths = module.derive_refmod_paths(
        project_dir=project, comfyui_workspace=workspace, project_id="film-a",
        asset_id="hero", entity_id="hero", state="default", source_sha256=source_hash,
        concept_type="identity", video_vae_name="minimax_h3_video_vae_fp16.safetensors",
    )
    paths["model_library_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["model_library_path"].write_bytes(b"unindexed-existing-mod")
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors", "concept_type": "identity",
    })

    assert not result.success
    assert "collision" in result.error.lower()
    assert fake.submission_count == 0
    assert paths["model_library_path"].read_bytes() == b"unindexed-existing-mod"


def test_refmod_tool_reextracts_changed_source_without_overwriting_old_mod(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module
    from lib.narrative_assets import NarrativeAssets

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)
    tool = ComfyUIRefMod()
    inputs = {
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    }
    first = tool.execute(inputs)
    first_project_path = project / first.data["project_path"]
    (project / "assets/images/hero.png").write_bytes(b"revised-approved-sheet")

    second = tool.execute(inputs)

    assert second.success
    assert second.data["loader_name"] != first.data["loader_name"]
    assert first_project_path.is_file()
    assert (project / second.data["project_path"]).is_file()


def test_refmod_tool_blocks_missing_live_node_before_submission(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace, missing_node="MiniMaxH3RefModExtract")
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    })

    assert not result.success
    assert "MiniMaxH3RefModExtract" in result.error
    assert fake.submission_count == 0


def test_refmod_tool_rejects_asset_missing_from_project_catalog(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    workspace.mkdir()
    _catalog(project)
    fake = FakeComfyUIClient(workspace)
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": str(workspace), "server_url": "http://127.0.0.1:8290",
        "asset_id": "unapproved-person", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    })

    assert not result.success
    assert "unknown refmod source asset" in result.error.lower()
    assert fake.submission_count == 0


def test_refmod_tool_rejects_unshared_remote_workspace(tmp_path, monkeypatch):
    import tools.video.comfyui_refmod as module

    project = tmp_path / "projects" / "film-a"
    _catalog(project)
    fake = FakeComfyUIClient(tmp_path / "unshared")
    monkeypatch.setattr(module, "ComfyUIClient", lambda **kwargs: fake)

    result = ComfyUIRefMod().execute({
        "project_id": "film-a", "project_dir": str(project),
        "comfyui_workspace": r"\\render-node\ComfyUI", "server_url": "http://10.0.0.8:8188",
        "asset_id": "hero", "reference_path": "assets/images/hero.png",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
        "concept_type": "identity",
    })

    assert not result.success
    assert "local" in result.error.lower() or "shared" in result.error.lower()
