"""Frame-rate handling for the FFmpeg compose path.

The compose path used to normalise every segment to a hardcoded 30 fps,
silently transforming native 24 fps sources. These tests pin the requested
frame rate through the filter and the encoder flag alike.
"""

from __future__ import annotations

import pytest

from tools.video.video_compose import VideoCompose


def test_target_fps_prefers_input_then_edit_then_default():
    tool = VideoCompose()
    assert tool._target_fps({"fps": 24}, {}) == 24
    assert tool._target_fps({}, {"fps": 24}) == 24
    assert tool._target_fps({}, {}) == 30


def test_target_fps_ignores_unset_values():
    tool = VideoCompose()
    assert tool._target_fps({"fps": None}, {"fps": 24}) == 24
    assert tool._target_fps({}, {"fps": None}) == 30


def test_schema_declares_fps_input():
    spec = VideoCompose.input_schema["properties"]["fps"]
    assert spec["type"] == "integer"
    assert spec["minimum"] == 1
    assert spec["maximum"] == 120
    assert spec["default"] == 30


@pytest.mark.parametrize("has_audio", [True, False])
def test_ffmpeg_compose_uses_requested_fps(tmp_path, monkeypatch, has_audio):
    """The segment filter and the encoder flag must use the same frame rate."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"existence check only")
    output = tmp_path / "out.mp4"
    calls: list[list[str]] = []

    tool = VideoCompose()
    monkeypatch.setattr(tool, "run_command", lambda cmd, **kwargs: calls.append(list(cmd)))
    monkeypatch.setattr(tool, "_has_audio_stream", lambda path: has_audio)

    result = tool._compose(
        {
            "edit_decisions": {
                "cuts": [
                    {"source": str(source), "in_seconds": 0, "out_seconds": 1.0}
                ],
                "metadata": {},
            },
            "fps": 24,
            "output_path": str(output),
        }
    )

    assert result.success, result.error
    segment_cmd = calls[0]
    filter_arg = segment_cmd[segment_cmd.index("-filter:v") + 1]
    assert "fps=24" in filter_arg
    assert "fps=30" not in filter_arg
    assert segment_cmd[segment_cmd.index("-r") + 1] == "24"
