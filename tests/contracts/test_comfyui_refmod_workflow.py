"""Graph binding contract for project-scoped MiniMax H3 RefMods."""

import copy

import pytest

from tools._comfyui.refmod_workflow import build_refmod_workflow


def mod(asset_id: str, index: int = 1) -> dict[str, str]:
    return {
        "asset_id": asset_id,
        "loader_name": f"openmontage/project-a/{asset_id}",
        "concept_type": "identity",
        "state": "wet",
        "description": f"approved reference for {asset_id}",
        "prompt_label": f"<Picture {index}>",
    }


def reference_to_video_workflow(*, native_video: bool = False) -> dict:
    h3_inputs = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "audio_vae": ["4", 0],
        "prompt": "<Picture 1> walks through the scene.",
        "width": 960,
        "height": 544,
        "length": 73,
    }
    workflow = {
        "1": {"class_type": "HyperFlowLoader", "inputs": {"unet_name": "ref2va.gguf"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "h3-clip.safetensors"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "h3-video-vae.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "h3-audio-vae.safetensors"}},
        "5": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": h3_inputs,
        },
        "9": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["1", 0], "conditioning": ["5", 0]},
        },
    }
    if native_video:
        workflow["5"]["inputs"]["ref_videos.ref_video_0"] = ["video_ref_loader", 0]
        workflow["video_ref_loader"] = {
            "class_type": "LoadVideo",
            "inputs": {"video": ["motion_video", 0]},
        }
        workflow["motion_video"] = {"class_type": "ApprovedMotionReference", "inputs": {}}
    return workflow


def test_refmod_only_reference_to_video_needs_no_native_stills():
    workflow, ordered_asset_ids = build_refmod_workflow(
        reference_to_video_workflow(),
        refs=[mod("hero-wet")],
        operation="reference_to_video",
    )

    assert ordered_asset_ids == ["hero-wet"]
    assert workflow["refmod_loader_1"]["inputs"]["mod_1"] == (
        "openmontage/project-a/hero-wet"
    )
    assert workflow["refmod_text_encode_1"]["class_type"] == "MiniMaxH3RefModTextEncode"
    assert workflow["refmod_text_encode_1"]["inputs"]["mods"] == [
        "refmod_loader_1",
        0,
    ]
    assert workflow["refmod_text_encode_1"]["inputs"]["prompt"] == (
        "<Picture 1> walks through the scene."
    )
    assert workflow["5"]["inputs"]["prompt"] == ""
    assert workflow["refmod_text_encode_1"]["inputs"]["clip"] == ["2", 0]
    assert workflow["refmod_text_encode_1"]["inputs"]["vae"] == ["3", 0]
    assert workflow["9"]["inputs"]["conditioning"] == [
        "refmod_text_encode_1",
        0,
    ]


def test_no_refmods_returns_existing_workflow_without_changes():
    original = reference_to_video_workflow()

    workflow, ordered_asset_ids = build_refmod_workflow(
        original,
        refs=[],
        operation="reference_to_video",
    )

    assert workflow == original
    assert workflow is not original
    assert ordered_asset_ids == []


def test_refmod_graph_keeps_native_motion_inputs_and_prompt_order():
    original = reference_to_video_workflow(native_video=True)
    original_video_connection = copy.deepcopy(
        original["5"]["inputs"]["ref_videos.ref_video_0"]
    )
    shot_refmods = [mod("hero-wet", 1), mod("loc-master", 2)]

    with pytest.raises(ValueError, match="native image/motion references"):
        build_refmod_workflow(
            original,
            refs=shot_refmods,
            operation="reference_to_video",
        )

    assert original["5"]["inputs"]["ref_videos.ref_video_0"] == original_video_connection
    assert [ref["prompt_label"] for ref in shot_refmods] == ["<Picture 1>", "<Picture 2>"]


def test_refmod_graph_blocks_more_than_eight_mods_without_truncation():
    nine_mods = [mod(f"asset-{i}", i + 1) for i in range(9)]

    with pytest.raises(ValueError, match="at most 8 mapped assets per shot"):
        build_refmod_workflow(
            reference_to_video_workflow(),
            refs=nine_mods,
            operation="reference_to_video",
        )


def test_refmod_graph_rejects_native_still_mixed_with_project_mods():
    workflow = reference_to_video_workflow()
    workflow["5"]["inputs"]["ref_images.ref_image_0"] = ["approved_still", 0]
    workflow["approved_still"] = {
        "class_type": "LoadImage",
        "inputs": {"image": "approved-still.png"},
    }

    with pytest.raises(ValueError, match="native image/motion references"):
        build_refmod_workflow(
            workflow,
            refs=[mod("hero-wet")],
            operation="reference_to_video",
        )


def test_fl2va_keyframe_operation_rejects_refmods():
    fl2v_workflow = {
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {}},
        "9": {"class_type": "BasicGuider", "inputs": {"conditioning": ["5", 0]}},
    }

    with pytest.raises(ValueError, match="FL2VA"):
        build_refmod_workflow(
            fl2v_workflow,
            refs=[mod("hero")],
            operation="first_last_frame_to_video",
        )


def test_custom_h3_graph_without_ref2va_conditioning_is_blocked():
    custom = {
        "12": {"class_type": "BasicGuider", "inputs": {"conditioning": ["10", 0]}},
        "10": {"class_type": "SomeOtherConditioning", "inputs": {}},
    }

    with pytest.raises(ValueError, match="Ref2VA conditioning"):
        build_refmod_workflow(
            custom,
            refs=[mod("hero")],
            operation="reference_to_video",
        )


def test_existing_refmod_chain_must_connect_to_ref2va_conditioning():
    workflow = reference_to_video_workflow()
    workflow["existing_loader"] = {
        "class_type": "MiniMaxH3RefModsLoader",
        "inputs": {"mod_1": "old/mod", "strength_1": 1.0},
    }
    workflow["existing_apply"] = {
        "class_type": "MiniMaxH3RefModApply",
        "inputs": {
            "conditioning": ["9", 0],
            "mods": ["existing_loader", 0],
        },
    }

    with pytest.raises(ValueError, match="Text Encode"):
        build_refmod_workflow(
            workflow,
            refs=[mod("hero")],
            operation="reference_to_video",
        )


def test_refmod_prompt_label_must_match_text_encoder_order():
    mismatched = mod("hero-wet", 9)

    with pytest.raises(ValueError, match="prompt_label.*<Picture 1>"):
        build_refmod_workflow(
            reference_to_video_workflow(),
            refs=[mismatched],
            operation="reference_to_video",
        )


def test_project_refmods_reject_legacy_apply_only_custom_graphs():
    workflow = reference_to_video_workflow()
    workflow["legacy_loader"] = {
        "class_type": "MiniMaxH3RefModsLoader",
        "inputs": {"mod_1": "old/mod", "strength_1": 0.0},
    }
    workflow["legacy_apply"] = {
        "class_type": "MiniMaxH3RefModApply",
        "inputs": {
            "conditioning": ["5", 0],
            "mods": ["legacy_loader", 0],
            "retention": 0.0,
            "scramble_seed": 123,
        },
    }
    workflow["9"]["inputs"]["conditioning"] = ["legacy_apply", 0]

    with pytest.raises(ValueError, match="Text Encode"):
        build_refmod_workflow(
            workflow,
            refs=[mod("hero-wet")],
            operation="reference_to_video",
        )
