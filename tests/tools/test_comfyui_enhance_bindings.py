import pytest

from tools.enhancement.comfyui_enhance import ComfyUIEnhance


def _tool(tmp_path):
    return ComfyUIEnhance(client=object())


def _face_inputs(tmp_path):
    refs = []
    for name in ("face.png", "wardrobe.png"):
        path = tmp_path / name
        path.write_bytes(b"img")
        refs.append(str(path))
    source = tmp_path / "take.mp4"
    source.write_bytes(b"video")
    project = tmp_path / "project"
    (project / "assets/video/enhanced").mkdir(parents=True)
    return {
        "operation": "face_refine",
        "input_path": str(source),
        "output_path": str(project / "assets/video/enhanced/s1-take1-face-refine.mp4"),
        "project_dir": str(project),
        "reference_image_paths": refs,
        "prompt": "subject_definitions: ...",
    }


def test_unknown_operation_is_rejected(tmp_path):
    inputs = _face_inputs(tmp_path) | {"operation": "sharpen"}
    assert "operation" in ComfyUIEnhance._validate_inputs(inputs)


def test_face_refine_requires_exactly_two_references(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["reference_image_paths"] = inputs["reference_image_paths"][:1]
    assert "two reference images" in ComfyUIEnhance._validate_inputs(inputs)


def test_face_refine_requires_prompt(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["prompt"] = ""
    assert "prompt" in ComfyUIEnhance._validate_inputs(inputs)


def test_output_must_stay_inside_project_dir(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["output_path"] = str(tmp_path / "outside.mp4")
    assert "project" in ComfyUIEnhance._validate_inputs(inputs)


def test_face_refine_binds_every_required_node(tmp_path):
    inputs = _face_inputs(tmp_path)
    patches = ComfyUIEnhance._workflow_patches(
        "face_refine", inputs,
        source_fps=25.0,
        source_name=str(tmp_path / "take.mp4"),
        ref_names=["face.png", "wardrobe.png"],
        output_prefix="om_enhance/face_refine",
    )
    assert patches["1"]["video"] == str(tmp_path / "take.mp4")
    assert patches["6"]["image"] == "face.png"
    assert patches["7"]["image"] == "wardrobe.png"
    assert patches["9"]["prompt"] == inputs["prompt"]
    assert patches["2"]["select"] == "largest_face"
    assert patches["16"]["denoise"] == 0.4
    assert patches["17"]["noise_seed"] == 42
    assert patches["23"]["frame_rate"] == 25.0
    assert patches["23"]["filename_prefix"] == "om_enhance/face_refine"


def test_upscale_binds_source_and_dials(tmp_path):
    source = tmp_path / "take.mp4"
    source.write_bytes(b"video")
    project = tmp_path / "project"
    (project / "assets/video/enhanced").mkdir(parents=True)
    inputs = {
        "operation": "video_upscale",
        "input_path": str(source),
        "output_path": str(project / "assets/video/enhanced/s1-take1-upscale.mp4"),
        "project_dir": str(project),
        "resolution": 1080,
    }
    patches = ComfyUIEnhance._workflow_patches(
        "video_upscale", inputs,
        source_fps=24.0,
        source_name="uploaded.mp4",
        ref_names=[],
        output_prefix="om_enhance/seedvr2",
    )
    assert patches["21"]["file"] == "uploaded.mp4"
    assert patches["10"]["resolution"] == 1080
    assert patches["23"]["filename_prefix"] == "om_enhance/seedvr2"


def test_models_can_be_overridden(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["models"] = {"unet": "custom_unet.safetensors"}
    models = ComfyUIEnhance._merged_models(inputs)
    assert models["unet"] == "custom_unet.safetensors"
    assert models["clip"] == "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
