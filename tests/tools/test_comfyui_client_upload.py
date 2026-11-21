from pathlib import Path
from unittest.mock import Mock

import pytest

from tools._comfyui.client import ComfyUIClient


def test_upload_input_file_posts_to_input_folder(monkeypatch, tmp_path):
    video = tmp_path / "take.mp4"
    video.write_bytes(b"video")
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"name": "om_take.mp4", "subfolder": "", "type": "input"}
    post = Mock(return_value=response)
    monkeypatch.setattr("tools._comfyui.client.requests.post", post)
    client = ComfyUIClient(server_url="http://127.0.0.1:8188")
    name = client.upload_input_file(video, "om_take.mp4")
    assert name == "om_take.mp4"
    assert post.call_args.args[0].endswith("/upload/image")
    assert post.call_args.kwargs["files"]["image"][0] == "om_take.mp4"
    assert post.call_args.kwargs["files"]["image"][2] == "application/octet-stream"


def test_upload_input_file_rejects_non_input_storage(monkeypatch, tmp_path):
    video = tmp_path / "take.mp4"
    video.write_bytes(b"video")
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"name": "om_take.mp4", "subfolder": "", "type": "temp"}
    monkeypatch.setattr("tools._comfyui.client.requests.post", Mock(return_value=response))
    with pytest.raises(Exception):
        ComfyUIClient(server_url="http://127.0.0.1:8188").upload_input_file(video, "om_take.mp4")
