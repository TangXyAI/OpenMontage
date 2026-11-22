import jsonschema
import pytest

from schemas.artifacts import validate_artifact


def _manifest_with_refmod():
    return {
        "version": "1.0",
        "assets": [],
        "metadata": {
            "refmod_assets": {
                "hero-wet": {
                    "project_id": "film",
                    "entity_id": "hero",
                    "state": "wet",
                    "concept_type": "identity",
                    "project_path": "assets/refmods/hero-wet.safetensors",
                    "loader_name": "openmontage/film/hero-wet-a1b2c3d4",
                    "source_path": "assets/images/hero-wet.png",
                    "source_sha256": "a" * 64,
                    "refmod_sha256": "b" * 64,
                    "status": "ready",
                    "extractor": {
                        "tool": "comfyui_refmod",
                        "node": "MiniMaxH3RefModExtract",
                        "workflow_hash_sha256": "c" * 64,
                    },
                }
            },
            "refmod_usage": {
                "mode": "project_refmod",
                "route_id": "minimax_h3_local",
                "decision_id": "d-004",
            },
        },
    }


def test_asset_manifest_schema_accepts_project_refmod_provenance():
    validate_artifact("asset_manifest", _manifest_with_refmod())


def test_asset_manifest_schema_rejects_missing_refmod_hash():
    manifest = _manifest_with_refmod()
    del manifest["metadata"]["refmod_assets"]["hero-wet"]["refmod_sha256"]

    with pytest.raises(jsonschema.ValidationError, match="refmod_sha256"):
        validate_artifact("asset_manifest", manifest)


def test_asset_manifest_schema_rejects_invalid_refmod_status():
    manifest = _manifest_with_refmod()
    manifest["metadata"]["refmod_assets"]["hero-wet"]["status"] = "current-ish"

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("asset_manifest", manifest)


def test_asset_manifest_schema_rejects_invalid_refmod_usage_mode():
    manifest = _manifest_with_refmod()
    manifest["metadata"]["refmod_usage"]["mode"] = "implicit"

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("asset_manifest", manifest)


def test_legacy_asset_manifest_without_refmod_metadata_remains_valid():
    validate_artifact("asset_manifest", {"version": "1.0", "assets": []})
