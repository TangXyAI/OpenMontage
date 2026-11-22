import pytest

from tools.video.comfyui_refmod import derive_refmod_paths


def test_refmod_paths_are_project_scoped_and_include_content_hash(tmp_path):
    project = tmp_path / "projects" / "film-a"
    workspace = tmp_path / "comfy"
    paths = derive_refmod_paths(
        project_dir=project,
        comfyui_workspace=workspace,
        project_id="film-a",
        asset_id="hero/wet",
        entity_id="hero",
        state="wet",
        source_sha256="a" * 64,
        concept_type="identity",
        video_vae_name="minimax_h3_video_vae_fp16.safetensors",
    )

    assert paths["project_path"].is_relative_to(project / "assets" / "refmods")
    assert paths["model_library_path"].is_relative_to(workspace / "models" / "refmods")
    assert paths["loader_name"].startswith("openmontage/film-a/")
    assert "aaaaaaaaaaaa" in paths["loader_name"]


def test_refmod_paths_reject_traversal_and_invalid_hash(tmp_path):
    common = {
        "project_dir": tmp_path / "projects" / "film-a",
        "comfyui_workspace": tmp_path / "comfy",
        "asset_id": "hero",
        "entity_id": "hero",
        "state": "default",
        "concept_type": "identity",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
    }
    with pytest.raises(ValueError, match="project_id"):
        derive_refmod_paths(project_id="../outside", source_sha256="a" * 64, **common)
    with pytest.raises(ValueError, match="SHA-256"):
        derive_refmod_paths(project_id="film-a", source_sha256="bad", **common)


def test_refmod_path_signature_changes_with_concept_or_vae(tmp_path):
    common = {
        "project_dir": tmp_path / "projects" / "film-a",
        "comfyui_workspace": tmp_path / "comfy",
        "project_id": "film-a",
        "asset_id": "hero",
        "entity_id": "hero",
        "state": "default",
        "source_sha256": "a" * 64,
        "concept_type": "identity",
        "video_vae_name": "minimax_h3_video_vae_fp16.safetensors",
    }
    first = derive_refmod_paths(**common)
    other_vae = derive_refmod_paths(**{**common, "video_vae_name": "other_vae.safetensors"})
    other_concept = derive_refmod_paths(**{**common, "concept_type": "clothing"})
    other_entity = derive_refmod_paths(**{**common, "entity_id": "courier"})
    other_extension = derive_refmod_paths(**{**common, "refmod_extension_version": "0.2.8"})

    assert first["loader_name"] != other_vae["loader_name"]
    assert first["loader_name"] != other_concept["loader_name"]
    assert first["loader_name"] != other_entity["loader_name"]
    assert first["loader_name"] != other_extension["loader_name"]


def test_refmod_paths_accept_unicode_asset_and_state_ids(tmp_path):
    paths = derive_refmod_paths(
        project_dir=tmp_path / "projects" / "film-a",
        comfyui_workspace=tmp_path / "comfy",
        project_id="film-a",
        asset_id="萧景衡",
        entity_id="hero",
        state="湿衣",
        source_sha256="a" * 64,
        concept_type="identity",
        video_vae_name="minimax_h3_video_vae_fp16.safetensors",
    )

    assert paths["project_path"].is_relative_to(tmp_path / "projects" / "film-a")
    assert paths["loader_name"].startswith("openmontage/film-a/")


def test_refmod_paths_preserve_dotted_asset_ids_in_loader_filename(tmp_path):
    paths = derive_refmod_paths(
        project_dir=tmp_path / "projects" / "film-a",
        comfyui_workspace=tmp_path / "comfy",
        project_id="film-a",
        asset_id="hero.v2",
        entity_id="hero",
        state="wet.v2",
        source_sha256="a" * 64,
        concept_type="identity",
        video_vae_name="minimax_h3_video_vae_fp16.safetensors",
    )

    loader_basename = paths["loader_name"].rsplit("/", 1)[1]
    assert paths["model_library_path"].name == loader_basename + ".safetensors"
    assert paths["project_path"].name.endswith(".safetensors")
