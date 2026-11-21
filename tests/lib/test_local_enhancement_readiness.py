from pathlib import Path

from lib.local_enhancement_readiness import check_enhancement_readiness


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _env(tmp_path: Path, *, nodes=("ComfyUI-H3-FaceRefine", "comfyui-videohelpersuite", "seedvr2_videoupscaler"), models=None):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    for node in nodes:
        (root / "custom_nodes" / node).mkdir(parents=True, exist_ok=True)
    model_root = tmp_path / "models"
    for name in models or ():
        _write(model_root / name)
    return root, model_root


FACE_MODELS = (
    "Minimax-h3_Singularity_ref2va_v2_int8.safetensors",
    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "minimax_h3_video_vae_fp16.safetensors",
    "minimax_h3_audio_vae_fp32.safetensors",
    "MiniMax-H3/加速/PikaFlex-Turbo-8步高清多模态参考视频加速.safetensors",
    "face_yolov8n.pt",
)
SEEDVR_MODELS = ("seedvr2_ema_3b_fp8_e4m3fn.safetensors", "ema_vae_fp16.safetensors")


def test_both_routes_ready(tmp_path):
    root, models = _env(tmp_path, models=(*FACE_MODELS, *SEEDVR_MODELS))
    result = check_enhancement_readiness(root, [models], server_running=True)
    assert result["ready"] is True
    assert set(result["ready_routes"]) == {"face_refine", "video_upscale"}


def test_missing_face_node_only_blocks_face_route(tmp_path):
    root, models = _env(tmp_path, nodes=("seedvr2_videoupscaler",), models=(*FACE_MODELS, *SEEDVR_MODELS))
    result = check_enhancement_readiness(root, [models], server_running=True)
    assert result["routes"]["face_refine"]["ready"] is False
    assert result["routes"]["video_upscale"]["ready"] is True
    assert any("FaceRefine" in item for item in result["routes"]["face_refine"]["blockers"])


def test_missing_videohelpersuite_blocks_face_route(tmp_path):
    root, models = _env(tmp_path, nodes=("ComfyUI-H3-FaceRefine", "seedvr2_videoupscaler"), models=(*FACE_MODELS, *SEEDVR_MODELS))
    result = check_enhancement_readiness(root, [models], server_running=True)
    assert result["routes"]["face_refine"]["ready"] is False
    assert any("videohelpersuite" in item.lower() for item in result["routes"]["face_refine"]["blockers"])


def test_node_directory_match_is_case_insensitive(tmp_path):
    root, models = _env(tmp_path, nodes=("ComfyUI-H3-FaceRefine", "ComfyUI-VideoHelperSuite", "SeedVR2_VideoUpscaler"), models=(*FACE_MODELS, *SEEDVR_MODELS))
    result = check_enhancement_readiness(root, [models], server_running=True)
    assert result["routes"]["face_refine"]["ready"] is True
    assert result["routes"]["video_upscale"]["ready"] is True


def test_missing_seedvr2_dit_is_warning(tmp_path):
    root, models = _env(tmp_path, models=(*FACE_MODELS, "ema_vae_fp16.safetensors"))
    result = check_enhancement_readiness(root, [models], server_running=True)
    assert result["routes"]["video_upscale"]["ready"] is True
    assert any("3.16" in item for item in result["routes"]["video_upscale"]["warnings"])


def test_missing_seedvr2_vae_is_blocker(tmp_path):
    root, models = _env(tmp_path, models=(*FACE_MODELS, "seedvr2_ema_3b_fp8_e4m3fn.safetensors"))
    result = check_enhancement_readiness(root, [models], server_running=True)
    assert result["routes"]["video_upscale"]["ready"] is False


def test_missing_insightface_is_warning(tmp_path):
    root, models = _env(tmp_path, models=(*FACE_MODELS, *SEEDVR_MODELS))
    result = check_enhancement_readiness(root, [models], server_running=True)
    assert result["routes"]["face_refine"]["ready"] is True
    assert any("insightface" in item.lower() for item in result["routes"]["face_refine"]["warnings"])


def test_server_down_is_global_blocker_but_routes_keep_file_state(tmp_path):
    root, models = _env(tmp_path, models=(*FACE_MODELS, *SEEDVR_MODELS))
    result = check_enhancement_readiness(root, [models], server_running=False)
    assert result["ready"] is False
    assert result["routes"]["face_refine"]["ready"] is True
    assert any("server" in item.lower() for item in result["blockers"])
