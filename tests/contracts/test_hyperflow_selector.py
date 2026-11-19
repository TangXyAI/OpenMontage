from tools.video.comfyui_video import ComfyUIVideo
from tools.video.video_selector import VideoSelector


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


def test_first_last_frame_fallback_excludes_image_selector():
    fallback = VideoSelector().fallback_tools_for(
        {"operation": "first_last_frame_to_video"}
    )
    assert "image_selector" not in fallback


class _Flf2vCapableStub:
    name = "flf2v_capable"
    capability = "video_generation"
    provider = "stub"
    supports = {"first_last_frame_to_video": True}
    input_schema = {"properties": {}}


class _NoFlf2vStub:
    name = "no_flf2v"
    capability = "video_generation"
    provider = "stub"
    supports = {}
    input_schema = {"properties": {}}


def test_first_last_frame_to_video_filters_providers_without_support():
    selector = VideoSelector()
    filtered = selector._filter_candidates(
        {"operation": "first_last_frame_to_video"},
        [_NoFlf2vStub(), _Flf2vCapableStub()],
    )
    assert [tool.name for tool in filtered] == ["flf2v_capable"]
