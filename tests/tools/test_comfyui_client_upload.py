from pathlib import Path
from unittest.mock import Mock

import pytest

from tools._comfyui.client import ComfyUIClient, ComfyUIError


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


def test_get_node_info_returns_the_selected_servers_input_contract(monkeypatch):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {
        "MiniMaxH3RefModTextEncode": {
            "input": {
                "required": {"clip": ["CLIP"], "mods": ["H3_REF_MODS"], "prompt": ["STRING"]},
                "optional": {"vae": ["VAE"]},
            }
        }
    }
    get = Mock(return_value=response)
    monkeypatch.setattr("tools._comfyui.client.requests.get", get)
    client = ComfyUIClient(server_url="http://127.0.0.1:8290", capability="video")

    contract = client.get_node_info("MiniMaxH3RefModTextEncode")

    assert set(contract["input"]["required"]) == {"clip", "mods", "prompt"}
    assert get.call_args.args[0] == (
        "http://127.0.0.1:8290/object_info/MiniMaxH3RefModTextEncode"
    )


def test_check_node_inputs_reports_missing_selected_server_sockets(monkeypatch):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {
        "MiniMaxH3RefModTextEncode": {
            "input": {
                "required": {"clip": ["CLIP"], "prompt": ["STRING"]},
                "optional": {"vae": ["VAE"]},
            }
        }
    }
    monkeypatch.setattr("tools._comfyui.client.requests.get", Mock(return_value=response))
    client = ComfyUIClient(server_url="http://127.0.0.1:8290", capability="video")

    missing = client.check_node_inputs(
        "MiniMaxH3RefModTextEncode", {"clip", "mods", "prompt", "vae"}
    )

    assert missing == ["mods"]


def test_get_node_info_wraps_selected_server_request_failure(monkeypatch):
    from requests import ConnectionError

    monkeypatch.setattr(
        "tools._comfyui.client.requests.get",
        Mock(side_effect=ConnectionError("connection dropped")),
    )
    client = ComfyUIClient(server_url="http://127.0.0.1:8290", capability="video")

    with pytest.raises(ComfyUIError, match="MiniMaxH3RefModTextEncode"):
        client.check_node_inputs(
            "MiniMaxH3RefModTextEncode", {"clip", "mods", "prompt"}
        )
