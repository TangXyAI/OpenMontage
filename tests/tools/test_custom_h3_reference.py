from tools.video.comfyui_video import ComfyUIVideo


def test_custom_h3_reference_is_not_rejected_by_bundled_route_guard():
    result = ComfyUIVideo().execute({
        "prompt": "test", "operation": "reference_to_video",
        "model_family": "minimax_h3_local", "workflow_json": "{}",
    })
    assert "require output_node" in result.error
