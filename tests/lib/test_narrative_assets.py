from pathlib import Path

import pytest

from lib.narrative_assets import NarrativeAssets, validate_character_sheet


_REVIEW_DIMENSIONS = (
    "identity_wardrobe",
    "location_anchors",
    "camera_continuity",
    "light_and_look",
    "story_state",
)


def _write_media(root, *paths):
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"media")


def _review(root, *, dimensions=None, override_reason=None):
    _write_media(root, "assets/reviews/s01-sh01.png")
    result = {
        "dimensions": dimensions or {name: "pass" for name in _REVIEW_DIMENSIONS},
        "notes": {name: "Checked against the approved scene contract." for name in _REVIEW_DIMENSIONS},
        "evidence_paths": ["assets/reviews/s01-sh01.png"],
    }
    if override_reason is not None:
        result["override_reason"] = override_reason
    return result


def _catalog_with_selected_shot(root, *, shot_id="s01-sh01", scene_id="s01", take_id="take-a", strict=True, select=True, record_review=True):
    _write_media(root, "assets/images/hero-wet.png", f"assets/video/{take_id}.mp4")
    catalog = NarrativeAssets(root)
    catalog.put_asset("hero-wet", "character", "Courier in a soaked coat", "assets/images/hero-wet.png", state="wet")
    if strict:
        catalog.register_shot(shot_id, scene_id, continuity_contract_version="1.0")
    else:
        catalog.register_shot(shot_id, scene_id)
    catalog.link_assets(shot_id, ["hero-wet"])
    catalog.add_take(shot_id, take_id, f"assets/video/{take_id}.mp4", 4.0)
    if strict and record_review:
        catalog.record_continuity_review(shot_id, take_id, _review(root))
    if select:
        catalog.select_take(shot_id, take_id)
    return catalog


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


def test_scene_id_survives_multiple_shots_in_manifest(tmp_path):
    _write_media(tmp_path, "assets/images/hero.png", "assets/video/take-a.mp4", "assets/video/take-b.mp4")
    catalog = NarrativeAssets(tmp_path)
    catalog.put_asset("hero", "character", "Courier", "assets/images/hero.png")

    for shot_id, take_id in (("s01-sh01", "take-a"), ("s01-sh02", "take-b")):
        catalog.register_shot(shot_id, "s01", continuity_contract_version="1.0")
        catalog.link_assets(shot_id, ["hero"])
        catalog.add_take(shot_id, take_id, f"assets/video/{take_id}.mp4", 4.0)
        catalog.record_continuity_review(shot_id, take_id, _review(tmp_path))
        catalog.select_take(shot_id, take_id)

    manifest = catalog.asset_manifest()
    assert {asset["scene_id"] for asset in manifest["assets"]} == {"s01"}
    assert manifest["metadata"]["continuity_shots"] == {
        "s01-sh01": {"scene_id": "s01", "continuity_contract_version": "1.0"},
        "s01-sh02": {"scene_id": "s01", "continuity_contract_version": "1.0"},
    }


def test_legacy_catalog_scene_id_defaults_to_shot_id(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path, shot_id="shot-legacy", scene_id="shot-legacy", strict=False)
    manifest = catalog.asset_manifest()
    assert manifest["assets"][0]["scene_id"] == "shot-legacy"
    assert manifest["metadata"]["continuity_shots"]["shot-legacy"] == {"scene_id": "shot-legacy"}


def test_state_variants_share_entity_id_and_review_requires_all_dimensions(tmp_path):
    _write_media(tmp_path, "assets/images/hero-dry.png", "assets/images/hero-wet.png", "assets/video/take-a.mp4")
    catalog = NarrativeAssets(tmp_path)
    catalog.put_asset("hero-dry", "character", "Courier in a dry coat", "assets/images/hero-dry.png", state="dry", entity_id="hero")
    catalog.put_asset("hero-wet", "character", "Courier in a wet coat", "assets/images/hero-wet.png", state="wet", entity_id="hero")
    catalog.register_shot("s01-sh01", "s01", continuity_contract_version="1.0")
    catalog.link_assets("s01-sh01", ["hero-wet"])
    catalog.add_take("s01-sh01", "take-a", "assets/video/take-a.mp4", 4.0)

    assert catalog.data["assets"]["hero-wet"]["entity_id"] == "hero"
    incomplete = {"dimensions": {name: "pass" for name in _REVIEW_DIMENSIONS[:-1]}}
    with pytest.raises(ValueError, match="story_state"):
        catalog.record_continuity_review("s01-sh01", "take-a", incomplete)


def test_review_drift_can_be_recorded_for_candidate_audit(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path, select=False, record_review=False)
    dimensions = {name: "pass" for name in _REVIEW_DIMENSIONS}
    dimensions["location_anchors"] = "drift"
    review = _review(tmp_path, dimensions=dimensions)

    catalog.record_continuity_review("s01-sh01", "take-a", review)
    saved_review = catalog.data["shots"]["s01-sh01"]["takes"]["take-a"]["metadata"]["continuity_review"]
    assert saved_review["dimensions"]["location_anchors"] == "drift"
    assert Path(saved_review["reviewed_path"]).as_posix() == "assets/video/take-a.mp4"


def test_select_take_rejects_strict_candidate_without_review(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path, select=False, record_review=False)

    with pytest.raises(ValueError, match="continuity review"):
        catalog.select_take("s01-sh01", "take-a")

    catalog.record_continuity_review("s01-sh01", "take-a", _review(tmp_path))
    catalog.select_take("s01-sh01", "take-a")
    assert catalog.data["shots"]["s01-sh01"]["selected"] == "take-a"


def test_select_take_rejects_drift_without_override_and_accepts_recorded_override(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path, select=False, record_review=False)
    dimensions = {name: "pass" for name in _REVIEW_DIMENSIONS}
    dimensions["location_anchors"] = "drift"
    review = _review(tmp_path, dimensions=dimensions)
    catalog.record_continuity_review("s01-sh01", "take-a", review)

    with pytest.raises(ValueError, match="override"):
        catalog.select_take("s01-sh01", "take-a")

    catalog.record_continuity_review("s01-sh01", "take-a", {**review, "override_reason": "Approved dream beat."})
    catalog.select_take("s01-sh01", "take-a")


def test_review_rejects_unknown_dimension_keys(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path)
    review = _review(tmp_path)
    review["dimensions"]["costume"] = "pass"

    with pytest.raises(ValueError, match="unsupported dimension"):
        catalog.record_continuity_review("s01-sh01", "take-a", review)


def test_review_rejects_blank_override_reason(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path)
    review = _review(tmp_path)
    review["override_reason"] = "  "

    with pytest.raises(ValueError, match="override"):
        catalog.record_continuity_review("s01-sh01", "take-a", review)


def test_enhancement_invalidates_review_of_previous_path(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path)
    catalog.record_continuity_review("s01-sh01", "take-a", _review(tmp_path))
    assert "s01-sh01" in catalog.asset_manifest()["metadata"]["continuity_reviews"]

    _write_media(tmp_path, "assets/video/enhanced/take-a-relayvsr.mp4")
    catalog.apply_enhancement(
        "s01-sh01",
        "take-a",
        "assets/video/enhanced/take-a-relayvsr.mp4",
        duration_seconds=4.0,
        enhancement={"operation": "relayvsr", "model": "RelayVSR", "source_path": "assets/video/take-a.mp4"},
    )

    assert "s01-sh01" not in catalog.asset_manifest()["metadata"]["continuity_reviews"]


def test_reapplying_enhancement_to_same_path_invalidates_current_review(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path)
    output = "assets/video/enhanced/take-a.mp4"
    _write_media(tmp_path, output)
    catalog.apply_enhancement(
        "s01-sh01", "take-a", output, duration_seconds=4.0,
        enhancement={"operation": "video_upscale", "model": "Upscaler", "source_path": "assets/video/take-a.mp4"},
    )
    catalog.record_continuity_review("s01-sh01", "take-a", _review(tmp_path))
    (tmp_path / output).write_bytes(b"different enhanced frames")

    catalog.apply_enhancement(
        "s01-sh01", "take-a", output, duration_seconds=4.0,
        enhancement={"operation": "video_upscale", "model": "Upscaler-v2", "source_path": output},
    )

    assert "continuity_review" not in catalog.data["shots"]["s01-sh01"]["takes"]["take-a"]["metadata"]
    assert "s01-sh01" not in catalog.asset_manifest()["metadata"]["continuity_reviews"]


def test_export_rejects_selected_drift_review_without_override(tmp_path):
    catalog = _catalog_with_selected_shot(tmp_path)
    dimensions = {name: "pass" for name in _REVIEW_DIMENSIONS}
    dimensions["location_anchors"] = "drift"
    catalog.record_continuity_review("s01-sh01", "take-a", _review(tmp_path, dimensions=dimensions))

    with pytest.raises(ValueError, match="override"):
        catalog.asset_manifest()


def _refmod_catalog(root):
    _write_media(
        root,
        "assets/images/hero-wet.png",
        "assets/images/location.png",
        "assets/refmods/hero-wet.safetensors",
        "assets/refmods/location.safetensors",
    )
    catalog = NarrativeAssets(root)
    catalog.put_asset("hero-wet", "character", "Courier in a soaked coat", "assets/images/hero-wet.png", state="wet", entity_id="hero")
    catalog.put_asset("loc-master", "location", "Empty workshop", "assets/images/location.png", state="master_plate", entity_id="loc-workshop")
    catalog.register_shot("s01-sh01", "s01")
    catalog.link_assets("s01-sh01", ["hero-wet", "loc-master"])
    return catalog


def _register_refmod(catalog, asset_id, project_path, loader_name, concept_type):
    catalog.register_refmod_asset(
        asset_id,
        project_id="film",
        project_path=project_path,
        loader_name=loader_name,
        concept_type=concept_type,
        source_sha256=catalog._sha256(
            catalog.root / catalog.data["assets"][asset_id]["path"]
        ),
        extractor={
            "tool": "comfyui_refmod",
            "node": "MiniMaxH3RefModExtract",
            "workflow_hash_sha256": "c" * 64,
        },
    )


def test_refmod_registration_exports_source_and_mod_hashes(tmp_path):
    import hashlib

    catalog = _refmod_catalog(tmp_path)
    _register_refmod(
        catalog, "hero-wet", "assets/refmods/hero-wet.safetensors",
        "openmontage/film/hero-wet-a1b2c3d4", "identity",
    )

    record = catalog.asset_manifest()["metadata"]["refmod_assets"]["hero-wet"]
    assert record["entity_id"] == "hero"
    assert record["state"] == "wet"
    assert record["source_sha256"] == hashlib.sha256(b"media").hexdigest()
    assert record["refmod_sha256"] == hashlib.sha256(b"media").hexdigest()
    assert record["status"] == "ready"


def test_refmod_registration_rejects_paths_outside_project(tmp_path):
    catalog = _refmod_catalog(tmp_path / "project")
    outside = tmp_path / "outside.safetensors"
    outside.write_bytes(b"outside Mod")

    with pytest.raises(ValueError, match="inside the project"):
        _register_refmod(
            catalog, "hero-wet", str(outside),
            "openmontage/film/hero-wet-a1b2c3d4", "identity",
        )


def test_refmod_registration_rejects_loader_name_traversal(tmp_path):
    catalog = _refmod_catalog(tmp_path)

    with pytest.raises(ValueError, match="loader"):
        _register_refmod(
            catalog, "hero-wet", "assets/refmods/hero-wet.safetensors",
            "openmontage/film/../other/mod", "identity",
        )


def test_refmod_registration_rejects_unknown_extractor_fields(tmp_path):
    catalog = _refmod_catalog(tmp_path)

    with pytest.raises(ValueError, match="extractor"):
        catalog.register_refmod_asset(
            "hero-wet",
            project_id="film",
            project_path="assets/refmods/hero-wet.safetensors",
            loader_name="openmontage/film/hero-wet-a1b2c3d4",
            concept_type="identity",
            source_sha256=catalog._sha256(
                catalog.root / catalog.data["assets"]["hero-wet"]["path"]
            ),
            extractor={
                "tool": "comfyui_refmod",
                "node": "MiniMaxH3RefModExtract",
                "workflow_hash_sha256": "c" * 64,
                "untracked_private_field": "must not leak into manifest",
            },
        )


def test_refmod_registration_rejects_malformed_extractor_hash(tmp_path):
    catalog = _refmod_catalog(tmp_path)

    with pytest.raises(ValueError, match="workflow_hash_sha256"):
        catalog.register_refmod_asset(
            "hero-wet",
            project_id="film",
            project_path="assets/refmods/hero-wet.safetensors",
            loader_name="openmontage/film/hero-wet-a1b2c3d4",
            concept_type="identity",
            source_sha256=catalog._sha256(
                catalog.root / catalog.data["assets"]["hero-wet"]["path"]
            ),
            extractor={
                "tool": "comfyui_refmod",
                "node": "MiniMaxH3RefModExtract",
                "workflow_hash_sha256": "not-a-hash",
            },
        )


def test_refmods_for_shot_returns_only_current_linked_mods_in_stable_order(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    _register_refmod(
        catalog, "hero-wet", "assets/refmods/hero-wet.safetensors",
        "openmontage/film/hero-wet-a1b2c3d4", "identity",
    )
    _register_refmod(
        catalog, "loc-master", "assets/refmods/location.safetensors",
        "openmontage/film/location-e5f6a7b8", "background",
    )

    refs = catalog.refmods_for_shot("s01-sh01")
    assert [item["asset_id"] for item in refs] == ["hero-wet", "loc-master"]
    assert [item["prompt_label"] for item in refs] == ["<Picture 1>", "<Picture 2>"]
    assert [item["description"] for item in refs] == ["Courier in a soaked coat", "Empty workshop"]


def test_refmods_for_shot_blocks_when_source_hash_changes(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    _register_refmod(
        catalog, "hero-wet", "assets/refmods/hero-wet.safetensors",
        "openmontage/film/hero-wet-a1b2c3d4", "identity",
    )
    catalog.record_refmod_usage(
        "project_refmod", route_id="hyperflow_gguf", decision_id="d-001"
    )
    (tmp_path / "assets/images/hero-wet.png").write_bytes(b"updated approved sheet")

    with pytest.raises(ValueError, match="stale RefMod"):
        catalog.refmods_for_shot("s01-sh01")
    assert catalog.asset_manifest()["metadata"]["refmod_assets"]["hero-wet"]["status"] == "stale"


def test_project_refmod_mode_blocks_a_missing_linked_asset_mapping(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    _register_refmod(
        catalog,
        "hero-wet",
        "assets/refmods/hero-wet.safetensors",
        "openmontage/film/hero-wet-a1b2c3d4",
        "identity",
    )
    catalog.record_refmod_usage(
        "project_refmod", route_id="hyperflow_gguf", decision_id="d-001"
    )

    with pytest.raises(ValueError, match="missing RefMod.*loc-master"):
        catalog.refmods_for_shot("s01-sh01")


def test_refmods_for_shot_marks_state_variant_change_stale(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    _register_refmod(
        catalog,
        "hero-wet",
        "assets/refmods/hero-wet.safetensors",
        "openmontage/film/hero-wet-a1b2c3d4",
        "identity",
    )
    catalog.record_refmod_usage(
        "project_refmod", route_id="hyperflow_gguf", decision_id="d-001"
    )
    catalog.data["assets"]["hero-wet"]["state"] = "dry"
    catalog._save()
    catalog = type(catalog)(tmp_path)

    with pytest.raises(ValueError, match="stale RefMod.*hero-wet"):
        catalog.refmods_for_shot("s01-sh01")
    assert catalog.asset_manifest()["metadata"]["refmod_assets"]["hero-wet"]["status"] == "stale"


def test_refmods_for_shot_checks_loader_copy_hash_when_workspace_is_known(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    catalog.link_assets("s01-sh01", ["hero-wet"])
    loader_name = "openmontage/film/hero-wet-a1b2c3d4"
    _register_refmod(
        catalog,
        "hero-wet",
        "assets/refmods/hero-wet.safetensors",
        loader_name,
        "identity",
    )
    catalog.record_refmod_usage(
        "project_refmod", route_id="hyperflow_gguf", decision_id="d-001"
    )
    workspace = tmp_path / "comfy"
    loader_copy = workspace / "models" / "refmods" / f"{loader_name}.safetensors"
    loader_copy.parent.mkdir(parents=True)
    loader_copy.write_bytes((tmp_path / "assets/refmods/hero-wet.safetensors").read_bytes())

    refs = catalog.refmods_for_shot("s01-sh01", comfyui_workspace=workspace)
    assert [item["asset_id"] for item in refs] == ["hero-wet"]

    loader_copy.write_bytes(b"changed loader copy")
    with pytest.raises(ValueError, match="stale RefMod.*hero-wet"):
        catalog.refmods_for_shot("s01-sh01", comfyui_workspace=workspace)


def test_native_ref2va_mode_does_not_require_project_mods(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    catalog.record_refmod_usage(
        "native_ref2va", route_id="hyperflow_gguf", decision_id="d-001"
    )

    assert catalog.refmods_for_shot("s01-sh01") == []


def test_refmod_registration_rejects_loader_from_another_project(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    with pytest.raises(ValueError, match="project_id"):
        catalog.register_refmod_asset(
            "hero-wet",
            project_id="film",
            project_path="assets/refmods/hero-wet.safetensors",
            loader_name="openmontage/another-project/hero-wet",
            concept_type="identity",
            source_sha256=catalog._sha256(
                catalog.root / catalog.data["assets"]["hero-wet"]["path"]
            ),
            extractor={
                "tool": "comfyui_refmod",
                "node": "MiniMaxH3RefModExtract",
                "workflow_hash_sha256": "c" * 64,
            },
        )


def test_refmod_usage_is_exported_with_decision_link(tmp_path):
    catalog = _refmod_catalog(tmp_path)
    catalog.record_refmod_usage(
        "project_refmod", route_id="minimax_h3_local", decision_id="d-004",
    )

    assert catalog.asset_manifest()["metadata"]["refmod_usage"] == {
        "mode": "project_refmod",
        "route_id": "minimax_h3_local",
        "decision_id": "d-004",
    }
