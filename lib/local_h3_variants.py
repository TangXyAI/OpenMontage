"""Discover the locally installed MiniMax H3 checkpoints and their workflows.

The user selects a variant; this module only reports what is installed. It
distinguishes a checkpoint that can run now (an API-format workflow exists)
from one that is installed but needs its UI workflow exported first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

LOCAL_H3_DECISION_SUBJECT = "Local H3 variant"

_DEFAULT_MODEL_ROOTS = (
    Path(r"G:/ComfyUI/Shared/models/diffusion_models"),
    Path(r"G:/ComfyUI/Installs/ComfyUI/ComfyUI/models/diffusion_models"),
)
_DEFAULT_WORKFLOW_ROOTS = (
    Path(r"G:/ComfyUI/Shared/workflows/MiniMaxH3"),
    Path(r"G:/ComfyUI/Installs/ComfyUI/ComfyUI/user/comfytv/workflows/video"),
)
_DEFAULT_BUNDLED = Path(__file__).resolve().parent.parent / "tools" / "_comfyui" / "workflows"

_H3_TOKENS = ("minimax", "h3", "singularity", "dasiwa")
_EXCLUDE_TOKENS = (
    "qwen",
    "z_image",
    "seedvr",
    "moss",
    "relayvsr",
    "krea",
    "flux",
    "image_edit",
    "audio_vae",
    "video_vae",
)
_FAMILY_RANK = {
    "HyperFlow": 0,
    "DaSiWa H3": 1,
    "Singularity 10Eros": 2,
    "Singularity": 3,
    "H3 Hybrid": 4,
    "H3 Base": 5,
}
_OP_TOKENS = {
    "t2v": ("t2v", "fl2v", "flf2v"),
    "i2v": ("i2v",),
    "flf2v": ("fl2v", "flf2v", "f2v"),
    "ref2v": ("r2v", "ref2v", "r2va"),
}


def _as_roots(value) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    return [Path(item) for item in value]


def _is_h3_checkpoint(path: Path) -> bool:
    if path.suffix.lower() not in {".safetensors", ".gguf"}:
        return False
    lower = path.name.lower()
    return any(token in lower for token in _H3_TOKENS) and not any(
        token in lower for token in _EXCLUDE_TOKENS
    )


def _family(name: str) -> str:
    lower = name.lower()
    if "hyperflow" in lower:
        return "HyperFlow"
    if "dasiwa" in lower:
        return "DaSiWa H3"
    if "singularity" in lower and "10eros" in lower:
        return "Singularity 10Eros"
    if "singularity" in lower:
        return "Singularity"
    if "hybrid" in lower:
        return "H3 Hybrid"
    return "H3 Base"


def _quantization(name: str, suffix: str) -> str:
    lower = name.lower()
    if suffix == ".gguf":
        return "gguf"
    for token in ("nvfp4", "int8", "fp8", "bf16", "fp16"):
        if token in lower:
            return token
    return "unknown"


def _operations(name: str, family: str) -> list[str]:
    lower = name.lower()
    if family == "HyperFlow":
        return ["ref2v"] if "ref2va" in lower else ["t2v", "i2v", "flf2v"]
    if "ref2va" in lower and "fl2va" not in lower:
        return ["ref2v"]
    if family == "Singularity 10Eros":
        return ["t2v", "i2v", "ref2v"]
    if family == "DaSiWa H3" or "hybrid" in lower or (
        "fl2va" in lower and "ref2va" in lower
    ):
        return ["t2v", "i2v", "flf2v", "ref2v"]
    return ["t2v", "i2v"]


def _workflow_format(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unknown"
    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        return "ui"
    if isinstance(data, dict):
        for key, node in data.items():
            if str(key).isdigit() and isinstance(node, dict) and "class_type" in node:
                return "api"
    return "unknown"


def _workflow_files(roots: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.json")))
    return files


def _find_workflow(
    name: str,
    family: str,
    operations: Sequence[str],
    roots: Sequence[Path],
) -> Path | None:
    token_groups: list[tuple[tuple[str, ...], int]] = []
    if family == "DaSiWa H3":
        token_groups = [(("dasiwa",), 20)]
    elif family == "Singularity 10Eros":
        token_groups = [(("10eros",), 20), (("singularity",), 10)]
    elif family == "Singularity":
        token_groups = [(("singularity",), 10)]
    elif family == "H3 Hybrid":
        token_groups = [
            (("local-minimax-h3",), 20),
            (("hybrid",), 20),
            (("minimax_h3",), 10),
        ]
    else:
        token_groups = [(("local-minimax-h3",), 20), (("minimax_h3",), 10)]
    op_tokens = {token for op in operations for token in _OP_TOKENS.get(op, ())}

    best: tuple[int, str, Path] | None = None
    for path in _workflow_files(roots):
        relative = path.as_posix().lower()
        score = 0
        for group, weight in token_groups:
            if any(token in relative for token in group):
                score = max(score, weight)
        if score == 0:
            continue
        if family == "Singularity" and "10eros" in relative:
            score -= 5
        if any(token in relative for token in op_tokens):
            score += 4
        if "未测试" in relative or "untested" in relative:
            score -= 2
        candidate = (score, path.name.lower(), path)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else None


def _bundled_hyperflow(name: str, bundled_dir: Path) -> Path | None:
    filename = (
        "hyperflow_int8_ref2v_api.json"
        if "ref2va" in name.lower()
        else "hyperflow_int8_t2v_api.json"
    )
    candidate = bundled_dir / filename
    return candidate if candidate.is_file() else None


def _slug(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def build_local_h3_menu(
    model_roots: Iterable[str | Path] | None = None,
    workflow_roots: Iterable[str | Path] | None = None,
    *,
    bundled_workflow_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List every installed local H3 checkpoint, including non-runnable ones."""
    roots = (
        list(_DEFAULT_MODEL_ROOTS)
        if model_roots is None
        else _as_roots(model_roots)
    )
    workflows = (
        list(_DEFAULT_WORKFLOW_ROOTS)
        if workflow_roots is None
        else _as_roots(workflow_roots)
    )
    bundled = Path(bundled_workflow_dir) if bundled_workflow_dir else _DEFAULT_BUNDLED

    seen: set[Path] = set()
    used_ids: set[str] = set()
    menu: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or not _is_h3_checkpoint(path):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            stem = path.stem
            family = _family(path.name)
            operations = _operations(path.name, family)
            quantization = _quantization(path.name, path.suffix.lower())
            if family == "HyperFlow":
                workflow = _bundled_hyperflow(path.name, bundled) or _find_workflow(
                    path.name, family, operations, workflows
                )
            else:
                workflow = _find_workflow(path.name, family, operations, workflows)
            workflow_format = _workflow_format(workflow)
            runnable = workflow_format == "api"
            if workflow is None:
                setup = "No matching H3 workflow found; add or export an API-format workflow."
            elif workflow_format == "ui":
                setup = (
                    f"Workflow is UI format; export '{workflow.name}' to API format "
                    "in ComfyUI (Dev mode → Export API)."
                )
            else:
                setup = None
            base_id = _slug(stem) or "h3-variant"
            variant_id = base_id
            suffix = 2
            while variant_id in used_ids:
                variant_id = f"{base_id}-{suffix}"
                suffix += 1
            used_ids.add(variant_id)
            menu.append(
                {
                    "variant_id": variant_id,
                    "label": f"{family} — {stem}",
                    "family": family,
                    "quantization": quantization,
                    "operations": operations,
                    "size_gb": round(path.stat().st_size / 1e9, 2),
                    "path": str(path),
                    "workflow": str(workflow) if workflow else None,
                    "workflow_format": workflow_format,
                    "runnable": runnable,
                    "setup": setup,
                    "notes": (
                        "Bundled HyperFlow API workflow (4/6/8-step accelerated)."
                        if family == "HyperFlow" and runnable
                        else "Installed; workflow found but UI-only."
                        if workflow_format == "ui"
                        else "Installed; no runnable API workflow."
                    ),
                }
            )
    menu.sort(
        key=lambda item: (
            not item["runnable"],
            _FAMILY_RANK.get(item["family"], 99),
            item["label"].lower(),
        )
    )
    return menu


def render_local_h3_menu(menu: Sequence[dict[str, Any]]) -> str:
    lines = ["Local MiniMax H3 variants (installed):"]
    for index, item in enumerate(menu, 1):
        status = "RUNNABLE" if item["runnable"] else "INSTALLED (not runnable)"
        lines.append(
            f"{index}. {item['label']} · {item['quantization']} · "
            f"{item['size_gb']} GB · {', '.join(item['operations'])} · {status}"
        )
        if item.get("setup"):
            lines.append(f"   setup: {item['setup']}")
    return "\n".join(lines)
