import json
from pathlib import Path

from lib.local_h3_variants import build_local_h3_menu, render_local_h3_menu


def _write(path: Path, text: str | bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, str):
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(text)


def _workflow(nodes: bool) -> str:
    return json.dumps({"nodes": []} if nodes else {"1": {"class_type": "X", "inputs": {}}})


def _fixture(tmp_path: Path):
    models = tmp_path / "models" / "diffusion_models"
    for name in (
        "minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors",
        "minimax_h3_ref2va_hyperflow_flash_14b-int8_convrot.safetensors",
        "Minimax-h3_Singularity_ref2va_v2_int8.safetensors",
        "Minimax-h3_Singularity_x_10Eros-Max_PRISM_int8.safetensors",
        "minimax_h3_dasiwa_hybridv4_int8.safetensors",
        "minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors",
        "qwen_image_edit_2511_int8_convrot.safetensors",
        "z_image_turbo_bf16.safetensors",
    ):
        _write(models / name, b"x" * 1024)
    _write(models / "krea2_turbo_fp8_scaled.safetensors.part", b"x")

    bundled = tmp_path / "bundled"
    _write(bundled / "hyperflow_int8_t2v_api.json", _workflow(nodes=False))
    _write(bundled / "hyperflow_int8_ref2v_api.json", _workflow(nodes=False))

    workflows = tmp_path / "workflows"
    _write(workflows / "Singularity" / "minimax_h3_singularity_V2_r2va.json", _workflow(nodes=True))
    _write(workflows / "Singularity" / "10eros_singularity_base1.json", _workflow(nodes=True))
    _write(workflows / "dasiwa-h3" / "DaSiWa MiniMaxH3.json", _workflow(nodes=True))
    _write(workflows / "local-minimax-h3-t2v.json", _workflow(nodes=True))
    return models, bundled, workflows


def _by_path(menu, needle):
    return next(item for item in menu if needle.lower() in item["path"].lower())


def test_lists_every_installed_h3_checkpoint_and_excludes_other_models(tmp_path):
    models, bundled, workflows = _fixture(tmp_path)
    menu = build_local_h3_menu([models], [workflows], bundled_workflow_dir=bundled)

    assert len(menu) == 6
    assert not any("qwen" in item["path"].lower() for item in menu)
    assert not any("z_image" in item["path"].lower() for item in menu)
    assert not any(item["path"].endswith(".part") for item in menu)

    hyperflow_fl = _by_path(menu, "fl2va_hyperflow")
    hyperflow_ref = _by_path(menu, "ref2va_hyperflow")
    assert hyperflow_fl["family"] == "HyperFlow"
    assert hyperflow_fl["quantization"] == "int8"
    assert hyperflow_fl["operations"] == ["t2v", "i2v", "flf2v"]
    assert hyperflow_fl["runnable"] is True
    assert hyperflow_fl["workflow_format"] == "api"
    assert hyperflow_fl["setup"] is None
    assert hyperflow_ref["operations"] == ["ref2v"]
    assert hyperflow_ref["runnable"] is True

    singularity = _by_path(menu, "Singularity_ref2va")
    assert singularity["family"] == "Singularity"
    assert singularity["operations"] == ["ref2v"]
    assert singularity["runnable"] is False
    assert singularity["workflow_format"] == "ui"
    assert "API" in singularity["setup"]

    eros = _by_path(menu, "10Eros")
    assert eros["family"] == "Singularity 10Eros"
    assert eros["runnable"] is False
    assert "10eros" in Path(eros["workflow"]).name.lower()

    dasiwa = _by_path(menu, "dasiwa")
    assert dasiwa["family"] == "DaSiWa H3"
    assert dasiwa["runnable"] is False
    assert "dasiwa" in Path(dasiwa["workflow"]).name.lower()

    hybrid = _by_path(menu, "hybrid_fl2va")
    assert hybrid["family"] == "H3 Hybrid"
    assert hybrid["operations"] == ["t2v", "i2v", "flf2v", "ref2v"]
    assert hybrid["runnable"] is False
    assert "local-minimax-h3" in Path(hybrid["workflow"]).name.lower()

    assert "10eros" not in Path(singularity["workflow"]).name.lower()


def test_every_installed_variant_is_rendered_with_status(tmp_path):
    models, bundled, workflows = _fixture(tmp_path)
    menu = build_local_h3_menu([models], [workflows], bundled_workflow_dir=bundled)
    rendered = render_local_h3_menu(menu)

    assert "Local MiniMax H3 variants" in rendered
    assert rendered.count("HyperFlow") >= 2
    assert "runnable" in rendered.lower()
    assert "installed (not runnable)" in rendered.lower()
    assert "export" in rendered.lower()


def test_variant_without_workflow_is_still_listed(tmp_path):
    models = tmp_path / "models" / "diffusion_models"
    _write(models / "minimax_h3_orphan_int8.safetensors")
    menu = build_local_h3_menu([models], [], bundled_workflow_dir=tmp_path / "empty")
    orphan = menu[0]
    assert orphan["runnable"] is False
    assert orphan["workflow"] is None
    assert "No matching H3 workflow" in orphan["setup"]
