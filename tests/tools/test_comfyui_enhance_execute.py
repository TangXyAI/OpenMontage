import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.base_tool import ToolResult
from tools.enhancement.comfyui_enhance import ComfyUIEnhance


class FakeClient:
    def __init__(self, when_generate=None):
        self.uploaded = []
        self.when_generate = when_generate

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    def upload_image(self, path, name):
        self.uploaded.append(("image", Path(path).name))
        return f"server-{Path(path).name}"

    def upload_input_file(self, path, name):
        self.uploaded.append(("video", Path(path).name))
        return f"server-{Path(path).name}"

    def generate(self, workflow, output_node, dest, *, timeout=600, interval=5, resume_prompt_id=None, on_progress=None):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"out")
        if self.when_generate:
            self.when_generate(workflow)
        return [Path(dest)]


def _inputs(tmp_path, operation="video_upscale"):
    source = tmp_path / "take.mp4"
    source.write_bytes(b"video")
    project = tmp_path / "project"
    (project / "assets/video/enhanced").mkdir(parents=True)
    return {
        "operation": operation,
        "input_path": str(source),
        "output_path": str(project / "assets/video/enhanced/out.mp4"),
        "project_dir": str(project),
    }


def _media_ok(path):
    return {"duration_seconds": 7.0, "video_fps": 24.0, "video_width": 640, "video_height": 352, "audio_streams": 1}


def test_upscale_uploads_source_and_reports_provenance(tmp_path, monkeypatch):
    captured = {}
    tool = ComfyUIEnhance(client=FakeClient(when_generate=lambda wf: captured.update(wf)))
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.91)
    result = tool.execute(_inputs(tmp_path))
    assert result.success, result.error
    assert captured["21"]["inputs"]["file"] == "server-take.mp4"
    assert result.data["provenance"]["workflow"] == "enhance_seedvr2_3b_api.json"
    assert result.data["validation"]["ssim"] == 0.91


def test_face_refine_uploads_two_refs(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path, "face_refine")
    refs = []
    for name in ("face.png", "wardrobe.png"):
        path = tmp_path / name
        path.write_bytes(b"img")
        refs.append(str(path))
    inputs |= {"reference_image_paths": refs, "prompt": "subject_definitions: ..."}
    client = FakeClient()
    tool = ComfyUIEnhance(client=client)
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.95)
    result = tool.execute(inputs)
    assert result.success, result.error
    assert [kind for kind, _ in client.uploaded] == ["image", "image"]


def test_audio_loss_fails_validation(tmp_path, monkeypatch):
    tool = ComfyUIEnhance(client=FakeClient())
    sources = {"src": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 1},
               "out": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 0}}
    paths = iter(["src", "out"])
    monkeypatch.setattr(tool, "_probe_media", lambda _: sources[next(paths)])
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9)
    result = tool.execute(_inputs(tmp_path))
    assert not result.success
    assert "audio" in result.error.lower()


def test_frame_rate_change_fails_validation(tmp_path, monkeypatch):
    tool = ComfyUIEnhance(client=FakeClient())
    sources = {"src": {"duration_seconds": 7.0, "video_fps": 30.0, "audio_streams": 1},
               "out": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 1}}
    paths = iter(["src", "out"])
    monkeypatch.setattr(tool, "_probe_media", lambda _: sources[next(paths)])
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9)
    result = tool.execute(_inputs(tmp_path))
    assert not result.success
    assert "frame rate" in result.error.lower()


def test_virtually_unchanged_output_returns_warning(tmp_path, monkeypatch):
    tool = ComfyUIEnhance(client=FakeClient())
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9995)
    result = tool.execute(_inputs(tmp_path))
    assert result.success
    assert "output_virtually_unchanged" in result.data["validation"]["warnings"]


def test_face_refine_fails_when_source_fps_unavailable(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path, "face_refine")
    refs = []
    for name in ("face.png", "wardrobe.png"):
        path = tmp_path / name
        path.write_bytes(b"img")
        refs.append(str(path))
    inputs |= {"reference_image_paths": refs, "prompt": "subject_definitions: ..."}
    tool = ComfyUIEnhance(client=FakeClient())
    monkeypatch.setattr(tool, "_probe_media", lambda _: {})
    result = tool.execute(inputs)
    assert not result.success
    assert "ffprobe" in result.error.lower() or "frame rate" in result.error.lower()


def test_timing_uses_design_keys(tmp_path, monkeypatch):
    class Timed(FakeClient):
        last_timing = {
            "client_queue_and_poll_s": 1.5,
            "comfy_prompt_exec_s": 2.5,
            "download_s": 0.5,
        }

    tool = ComfyUIEnhance(client=Timed())
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9)
    result = tool.execute(_inputs(tmp_path))
    assert result.success, result.error
    timing = result.data["timing"]
    assert timing["queue_seconds"] == 1.5
    assert timing["execution_seconds"] == 2.5
    assert timing["download_seconds"] == 0.5
    assert "wall_seconds" in timing
    assert timing["client_timing"]["download_s"] == 0.5


def test_upscale_warns_when_output_probe_unavailable(tmp_path, monkeypatch):
    tool = ComfyUIEnhance(client=FakeClient())
    monkeypatch.setattr(tool, "_probe_media", lambda _: {})
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: None)
    result = tool.execute(_inputs(tmp_path))
    assert result.success, result.error
    assert "media_probe_unavailable" in result.data["validation"]["warnings"]


def test_validation_failure_preserves_existing_output(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    output = Path(inputs["output_path"])
    output.write_bytes(b"ORIGINAL")
    tool = ComfyUIEnhance(client=FakeClient())
    sources = {
        "src": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 1},
        "out": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 0},
    }
    paths = iter(["src", "out"])
    monkeypatch.setattr(tool, "_probe_media", lambda _: sources[next(paths)])
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9)
    result = tool.execute(inputs)
    assert not result.success
    assert output.read_bytes() == b"ORIGINAL"
    assert list(output.parent.glob("*.partial*")) == []


def test_success_replaces_existing_output_and_cleans_partial(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    output = Path(inputs["output_path"])
    output.write_bytes(b"ORIGINAL")
    tool = ComfyUIEnhance(client=FakeClient())
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9)
    result = tool.execute(inputs)
    assert result.success, result.error
    assert output.read_bytes() == b"out"
    assert list(output.parent.glob("*.partial*")) == []


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required for a real SSIM check",
)
def test_compute_ssim_handles_different_dimensions(tmp_path):
    def make_clip(name, size):
        path = tmp_path / name
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=size={size}:rate=24:duration=0.5",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        return path

    small = make_clip("small.mp4", "64x36")
    large = make_clip("large.mp4", "128x72")
    value = ComfyUIEnhance._compute_ssim(small, large)
    assert isinstance(value, float)


def test_unavailable_server_fails_without_fallback(tmp_path):
    class Down(FakeClient):
        def is_available(self):
            return False
        def unavailable_reason(self):
            return "ComfyUI server not reachable"
    result = ComfyUIEnhance(client=Down()).execute(_inputs(tmp_path))
    assert not result.success
    assert "not reachable" in result.error
