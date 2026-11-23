from tools.enhancement.comfyui_enhance import ComfyUIEnhance


def test_relayvsr_binds_uploaded_video_and_output():
    inputs = {"operation": "relayvsr", "seed": 17}
    patches = ComfyUIEnhance._workflow_patches(
        "relayvsr", inputs, source_fps=24, source_name="clip.mp4",
        ref_names=[], output_prefix="project/relay",
    )
    assert patches["1"]["file"] == "clip.mp4"
    assert patches["6"]["seed"] == 17
    assert patches["10"]["filename_prefix"] == "project/relay"
    assert patches["3"]["unet_name"] == "relayvsr_x2_lightx2v_int8_convrot.safetensors"
    assert patches["7"]["vae_name"] == "relayvsr_flash_vae_x2_fp32.safetensors"
    assert "relayvsr" in ComfyUIEnhance.input_schema["properties"]["operation"]["enum"]
