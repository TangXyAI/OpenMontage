"""Contract tests against a local ComfyUI-compatible HTTP boundary."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from tools._comfyui.client import ComfyUIClient, ComfyUIError


@pytest.fixture
def comfy_server():
    state = {"uploads": 0, "prompts": [], "upload_type": "input", "media": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if self.path == "/upload/image":
                state["uploads"] += 1
                result = {"name": f"frame{state['uploads']}.png", "subfolder": "refs", "type": state["upload_type"]}
            else:
                state["prompts"].append(json.loads(body)["prompt"])
                result = {"prompt_id": f"p{len(state['prompts'])}", "number": 1, "node_errors": {}}
            payload = json.dumps(result).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path.startswith("/view"):
                name = parse_qs(urlparse(self.path).query).get("filename", [""])[0]
                payload = state["media"].get(name, b"video")
            elif self.path.startswith("/history/"):
                prompt_id = self.path.rsplit("/", 1)[-1]
                payload = json.dumps({prompt_id: {"outputs": {"9": {"images": [{"filename": f"{prompt_id}.mp4", "subfolder": "", "type": "output"}]}}}}).encode()
            else:
                payload = b"{}"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    thread.join()
    server.server_close()


def test_upload_preserves_server_subfolder_and_type(comfy_server, tmp_path):
    url, state = comfy_server
    image = tmp_path / "frame.png"
    image.write_bytes(b"png")
    client = ComfyUIClient(url)
    assert client.upload_image(image, "frame.png") == "refs/frame1.png"
    state["upload_type"] = "output"
    with pytest.raises(ComfyUIError):
        client.upload_image(image, "frame.png")


@pytest.mark.parametrize("target", [
    {"node": "missing", "input": "text"},
    {"node": "2", "input": "connected"},
    {"node": "1", "input": "image"},
])
def test_bindings_validate_all_targets_before_upload(comfy_server, tmp_path, target):
    url, state = comfy_server
    image = tmp_path / "frame.png"
    image.write_bytes(b"png")
    workflow = {"1": {"inputs": {"image": "old"}}, "2": {"inputs": {"connected": ["1", 0]}}}
    original = json.dumps(workflow, sort_keys=True)
    with pytest.raises(ComfyUIError):
        ComfyUIClient(url).bind_workflow(workflow, {
            "reference_image_path": [{"node": "1", "input": "image"}],
            "prompt": [target],
        }, {"reference_image_path": str(image), "prompt": "hello"})
    assert state["uploads"] == 0
    assert not state["prompts"]
    assert json.dumps(workflow, sort_keys=True) == original


def test_selector_passes_h3_bindings_and_multiple_images(comfy_server, tmp_path, monkeypatch):
    from tools.video.comfyui_video import ComfyUIVideo
    from tools.video.video_selector import VideoSelector

    url, state = comfy_server
    tool = ComfyUIVideo()
    tool._client.server_url = url
    monkeypatch.setattr(tool._client, "_wait", lambda prompt_id, **kwargs: tool._client.poll(prompt_id, timeout=1, interval=0))
    selector = VideoSelector()
    monkeypatch.setattr(selector, "_providers", lambda: [tool])
    for name in ("hero.png", "place.png"):
        (tmp_path / name).write_bytes(b"png")
    workflow = {"1": {"inputs": {"image": "old"}}, "2": {"inputs": {"image": "old"}}, "3": {"inputs": {"text": "old", "seed": 9}}, "4": {"inputs": {"link": ["3", 0]}}, "9": {"inputs": {}}}
    result = selector.execute({"prompt": "run", "seed": 0, "model_family": "minimax_h3_local", "workflow_json": json.dumps(workflow), "output_node": "9", "output_path": str(tmp_path / "out.mp4"), "reference_images": {"hero": str(tmp_path / "hero.png"), "place": str(tmp_path / "place.png")}, "workflow_bindings": {"reference_images.hero": [{"node": "1", "input": "image"}], "reference_images.place": [{"node": "2", "input": "image"}], "prompt": [{"node": "3", "input": "text"}], "seed": [{"node": "3", "input": "seed"}]}})
    assert result.success, result.error
    sent = state["prompts"][0]
    assert sent["1"]["inputs"]["image"] == "refs/frame1.png"
    assert sent["2"]["inputs"]["image"] == "refs/frame2.png"
    assert sent["3"]["inputs"] == {"text": "run", "seed": 0}
    assert sent["4"] == workflow["4"]


def test_resume_uses_existing_prompt_without_upload_or_submit(comfy_server, tmp_path, monkeypatch):
    from tools.video.comfyui_video import ComfyUIVideo

    url, state = comfy_server
    tool = ComfyUIVideo()
    tool._client.server_url = url
    def timeout(prompt_id, **kwargs):
        raise ComfyUIError("timed out", prompt_id=prompt_id)
    monkeypatch.setattr(tool._client, "_wait", timeout)
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png")
    inputs = {"prompt": "run", "model_family": "minimax_h3_local", "workflow_json": json.dumps({"1": {"inputs": {"image": "old"}}, "9": {"inputs": {}}}), "output_node": "9", "output_path": str(tmp_path / "out.mp4"), "reference_image_path": str(ref), "workflow_bindings": {"reference_image_path": [{"node": "1", "input": "image"}]}}
    first = tool.execute(inputs)
    assert not first.success and first.data["prompt_id"] == "p1"
    assert first.data["resume_context"]["workflow_provenance"]["workflow_hash_sha256"]
    ref.unlink()
    result = tool.execute({**inputs, "resume_prompt_id": "p1"})
    assert result.success, result.error
    assert len(state["prompts"]) == 1 and state["uploads"] == 1
    assert result.seed is None
    assert result.data["workflow_provenance"].get("workflow_hash_sha256") is None
    restored = tool.execute({**inputs, "resume_prompt_id": "p1", "resume_context": first.data["resume_context"]})
    assert restored.success
    assert restored.data["workflow_provenance"] == first.data["resume_context"]["workflow_provenance"]
    assert restored.seed == first.data["resume_context"]["seed"]


def test_h3_preflight_does_not_infer_readiness_from_wan_or_server(comfy_server):
    from tools.video.comfyui_video import ComfyUIVideo

    tool = ComfyUIVideo()
    tool._client.server_url = comfy_server[0]
    modes = tool.get_info()["execution_modes"]
    assert modes["minimax_h3_local"]["readiness"] == "unknown"
    assert modes["minimax_h3_api"]["hosted"] is True
