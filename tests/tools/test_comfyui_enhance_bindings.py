from tools.enhancement.comfyui_enhance import ComfyUIEnhance


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


def test_project_dir_is_required(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs.pop("project_dir")
    error = ComfyUIEnhance._validate_inputs(inputs)
    assert error is not None
    assert "project_dir" in error


def test_input_and_output_path_must_differ(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["output_path"] = inputs["input_path"]
    error = ComfyUIEnhance._validate_inputs(inputs)
    assert error is not None
    assert "input_path" in error
    assert "output_path" in error


def test_malformed_reference_list_is_rejected_without_raising(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["reference_image_paths"] = 5
    error = ComfyUIEnhance._validate_inputs(inputs)
    assert error is not None
    assert "reference_image_paths" in error


def test_malformed_path_type_is_rejected_without_raising(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["output_path"] = ["not", "a", "path"]
    error = ComfyUIEnhance._validate_inputs(inputs)
    assert isinstance(error, str)


def test_timeout_seconds_must_be_a_positive_integer(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["timeout_seconds"] = "soon"
    assert "timeout_seconds" in ComfyUIEnhance._validate_inputs(inputs)

    inputs["timeout_seconds"] = 0
    assert "timeout_seconds" in ComfyUIEnhance._validate_inputs(inputs)

    inputs["timeout_seconds"] = float("inf")
    assert "timeout_seconds" in ComfyUIEnhance._validate_inputs(inputs)


def test_estimate_runtime_uses_duration_seconds_and_duration():
    tool = ComfyUIEnhance(client=object())
    assert tool.estimate_runtime(
        {"operation": "face_refine", "duration_seconds": 3.0}
    ) == 300.0
    assert tool.estimate_runtime(
        {"operation": "video_upscale", "duration_seconds": 3.0}
    ) == 564.0
    assert tool.estimate_runtime({"operation": "video_upscale", "duration": 3.0}) == 564.0
    assert tool.estimate_runtime(
        {"operation": "face_refine", "duration_seconds": 0.0}
    ) == 120.0
    assert tool.estimate_runtime({"operation": "sharpen", "duration": 3.0}) == 0.0
    assert tool.estimate_runtime({}) == 0.0


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
