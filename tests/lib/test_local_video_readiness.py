"""Tests for the filesystem-only HyperFlow readiness checker."""

from lib.local_video_readiness import check_hyperflow_readiness


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_reports_ready_when_all_files_exist(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    for node in ("comfyui-hyperflow-flash", "comfyui-hyperflow-int8-nodes", "ComfyUI-GGUF"):
        (root / "custom_nodes" / node).mkdir(parents=True)
    models = tmp_path / "models"
    for name in (
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "minimax_h3_video_vae_fp16.safetensors",
        "minimax_h3_audio_vae_fp32.safetensors",
        "minimax_h3_sol_vae_int8_convrot.safetensors",
        "minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf",
        "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf",
    ):
        _write(models / name)
    result = check_hyperflow_readiness(root, [models], server_running=True)
    assert result["ready"] is True
    assert result["blockers"] == []


def test_missing_checkpoint_is_a_blocker(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=True)
    assert result["ready"] is False
    assert any("hyperflow" in item.lower() for item in result["blockers"])


def test_old_comfyui_is_a_blocker(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.42.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=True)
    assert any("0.43" in item for item in result["blockers"])


def test_missing_sol_vae_is_a_warning(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=False)
    assert any("sol" in item.lower() for item in result["warnings"])


def test_return_shape_and_check_entries(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=True)

    assert set(result) == {
        "ready", "comfyui_version", "checks", "blockers", "warnings",
    }
    assert result["comfyui_version"] == "0.45.0"
    for name, check in result["checks"].items():
        assert set(check) == {"ok", "path", "detail"}, name
        assert isinstance(check["ok"], bool), name
        assert check["path"] is None or isinstance(check["path"], str), name
        assert isinstance(check["detail"], str), name


def test_missing_comfyui_version_file_is_a_blocker(tmp_path):
    result = check_hyperflow_readiness(
        tmp_path / "ComfyUI", [tmp_path / "models"], server_running=True
    )
    assert result["ready"] is False
    assert result["comfyui_version"] is None
    assert any("0.43" in item for item in result["blockers"])


def test_stopped_server_is_a_blocker(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=False)
    assert result["ready"] is False
    assert any("server" in item.lower() for item in result["blockers"])


def test_missing_custom_node_pack_is_a_blocker(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    (root / "custom_nodes" / "comfyui-hyperflow-flash").mkdir(parents=True)
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=True)
    assert result["ready"] is False
    assert any("ComfyUI-GGUF" in item for item in result["blockers"])


def test_models_are_found_in_nested_directories(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    for node in ("comfyui-hyperflow-flash", "comfyui-hyperflow-int8-nodes", "ComfyUI-GGUF"):
        (root / "custom_nodes" / node).mkdir(parents=True)
    models = tmp_path / "models"
    _write(models / "text_encoders" / "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
    _write(models / "vae" / "minimax_h3_video_vae_fp16.safetensors")
    _write(models / "vae" / "minimax_h3_audio_vae_fp32.safetensors")
    _write(models / "vae" / "minimax_h3_sol_vae_int8_convrot.safetensors")
    _write(models / "diffusion_models" / "fl2va" / "minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf")
    _write(models / "diffusion_models" / "ref2va" / "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf")
    result = check_hyperflow_readiness(root, [models], server_running=True)
    assert result["ready"] is True, result["blockers"]
    assert result["checks"]["text_encoder"]["path"].endswith(
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    )


def test_blockers_name_the_searched_model_roots(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    models = tmp_path / "models"
    models.mkdir()
    result = check_hyperflow_readiness(root, [models], server_running=True)
    assert any(str(models) in item for item in result["blockers"])
