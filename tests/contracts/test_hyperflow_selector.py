from tools.video.comfyui_video import ComfyUIVideo


def test_hyperflow_operations_are_advertised():
    tool = ComfyUIVideo()
    tool._client.is_available = lambda: True
    for operation in ("first_last_frame_to_video", "reference_to_video"):
        assert tool.supports.get(operation) is True
        assert operation in tool.operation_statuses()
        assert tool.is_operation_available(operation) is True


def test_non_hyperflow_family_rejects_new_operations():
    result = ComfyUIVideo().execute({
        "prompt": "x", "model_family": "wan2.2",
        "operation": "reference_to_video",
        "output_path": "out.mp4",
    })
    assert not result.success
    assert "minimax_h3_hyperflow_local" in (result.error or "")
