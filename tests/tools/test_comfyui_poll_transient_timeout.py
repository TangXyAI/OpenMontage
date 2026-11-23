import pytest
import requests

from tools._comfyui.client import ComfyUIClient, ComfyUIError


def test_poll_retries_temporary_history_read_timeout(monkeypatch):
    client = ComfyUIClient(server_url="http://127.0.0.1:8290")
    calls = []

    def history(prompt_id):
        calls.append(prompt_id)
        if len(calls) == 1:
            raise requests.exceptions.ReadTimeout("busy")
        return {"status": {"status_str": "success"}}

    monkeypatch.setattr(client, "_history_entry", history)
    monkeypatch.setattr("tools._comfyui.client.time.sleep", lambda _: None)
    result = client.poll("existing-prompt", timeout=5, interval=0)
    assert result["status"]["status_str"] == "success"
    assert calls == ["existing-prompt", "existing-prompt"]


def test_poll_does_not_hide_comfyui_execution_failure(monkeypatch):
    client = ComfyUIClient(server_url="http://127.0.0.1:8290")

    def history(prompt_id):
        raise ComfyUIError("Execution error: invalid graph", prompt_id=prompt_id)

    monkeypatch.setattr(client, "_history_entry", history)
    with pytest.raises(ComfyUIError, match="invalid graph"):
        client.poll("existing-prompt", timeout=5, interval=0)
