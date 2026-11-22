from lib.checkpoint import write_checkpoint
from tests.contracts.test_narrative_continuity_workflow import (
    _compose_result,
    _one_shot_catalog,
    _proposal_checkpoint,
    _review,
    _write_asset_and_edit_checkpoints,
    _write_media,
)


def test_compose_rejects_missing_input_selection_metadata_for_strict_project(tmp_path):
    root = _proposal_checkpoint(tmp_path, strict=True)
    catalog = _one_shot_catalog(root, strict=True, review_status="pass")
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s01-sh01"], "ffmpeg")
    _write_asset_and_edit_checkpoints(tmp_path, manifest, edit)
    del edit["metadata"]["narrative_selection"]

    result = _compose_result(root, manifest, edit)

    assert not result.success
    assert "narrative selection" in result.error.lower()


def test_compose_rejects_checkpoint_cut_for_pre_enhancement_path(tmp_path):
    root = _proposal_checkpoint(tmp_path, strict=True)
    catalog = _one_shot_catalog(root, strict=True, review_status="pass")
    old_manifest = catalog.asset_manifest()
    old_edit = catalog.edit_decisions(["s01-sh01"], "ffmpeg")
    _write_asset_and_edit_checkpoints(tmp_path, old_manifest, old_edit)

    _write_media(root, "assets/video/enhanced/take-a.mp4")
    catalog.apply_enhancement(
        "s01-sh01", "take-a", "assets/video/enhanced/take-a.mp4", duration_seconds=4.0,
        enhancement={"operation": "video_upscale", "model": "Upscaler", "source_path": "assets/video/take-a.mp4"},
    )
    catalog.record_continuity_review("s01-sh01", "take-a", _review(root, "s01-sh01"))
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s01-sh01"], "ffmpeg")
    write_checkpoint(
        tmp_path, "film", "assets", "completed", {"asset_manifest": manifest},
        pipeline_type="cinematic", human_approval_required=True, human_approved=True,
    )

    result = _compose_result(root, manifest, edit)

    assert not result.success
    assert "edit" in result.error.lower() or "checkpoint" in result.error.lower()
