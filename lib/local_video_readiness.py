"""Filesystem-only readiness check for the local ComfyUI + HyperFlow stack.

The agent asks this helper whether a local HyperFlow route can run before it
offers that route to the user. The check is deliberately offline: it reads
ComfyUI's version file, the ``custom_nodes`` directory, and the configured
model roots. It never talks to the ComfyUI server, so it is safe to call
during preflight on a machine where ComfyUI is not running yet.

The result separates hard blockers (the local route cannot run) from warnings
(optional assets that only the fast INT8 workflow needs). HyperFlow ships in two
quantizations — GGUF (Q4_K_M) and INT8 (convrot safetensors) — and each is a
separate route in the menu, so the result also carries a per-variant map. A
machine with only the INT8 weights installed is ready for the INT8 route but not
for the GGUF route.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

MIN_COMFYUI_VERSION = (0, 43, 0)
MIN_COMFYUI_VERSION_TEXT = "0.43.0"

REQUIRED_CUSTOM_NODES = (
    "comfyui-hyperflow-flash",
    "comfyui-hyperflow-int8-nodes",
    "ComfyUI-GGUF",
)

# (check name, human label, exact basename)
REQUIRED_MODELS = (
    (
        "text_encoder",
        "text encoder",
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    ),
    ("video_vae", "video VAE", "minimax_h3_video_vae_fp16.safetensors"),
    ("audio_vae", "audio VAE", "minimax_h3_audio_vae_fp32.safetensors"),
)

# (checkpoint key, human label, canonical pattern, required name tokens)
#
# Each quantization is a distinct route in the menu, so each gets its own
# checkpoint set. ModelScope basenames put the variant first — ``minimax_h3_
# fl2va_hyperflow_flash_14b-Q4_K_M.gguf`` — so the tokens are matched in any
# order rather than with a single order-sensitive glob.
VARIANT_CHECKPOINTS = {
    "gguf": (
        (
            "fl2va",
            "HyperFlow fl2va GGUF checkpoint",
            "*hyperflow*fl2va*.gguf",
            ("hyperflow", "fl2va"),
        ),
        (
            "ref2va",
            "HyperFlow ref2va GGUF checkpoint",
            "*hyperflow*ref2va*.gguf",
            ("hyperflow", "ref2va"),
        ),
    ),
    "int8": (
        (
            "fl2va",
            "HyperFlow fl2va INT8 checkpoint",
            "*14b-int8_convrot.safetensors",
            ("hyperflow", "fl2va", "14b-int8_convrot"),
        ),
        (
            "ref2va",
            "HyperFlow ref2va INT8 checkpoint",
            "*14b-int8_convrot.safetensors",
            ("hyperflow", "ref2va", "14b-int8_convrot"),
        ),
    ),
}

# A variant file must carry the quantization's final extension. ``.part``
# downloads (``...gguf.part``) are incomplete and never satisfy the route.
VARIANT_SUFFIX = {"gguf": ".gguf", "int8": ".safetensors"}

SOL_VAE_CHECK = "sol_vae"
SOL_VAE_NAME = "minimax_h3_sol_vae_int8_convrot.safetensors"

_VERSION_PATTERN = re.compile(r'__version__\s*=\s*"([^"]+)"')


def _normalise_roots(model_roots: Sequence[str | Path] | str | Path) -> list[Path]:
    """Accept one root or a sequence of roots and return a list of paths."""
    if isinstance(model_roots, (str, Path)):
        return [Path(model_roots)]
    return [Path(root) for root in model_roots]


def _read_version(version_file: Path) -> str | None:
    """Return ``__version__`` from a ComfyUI version file, or None."""
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _VERSION_PATTERN.search(text)
    return match.group(1) if match else None


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Turn a dotted version into three comparable integers."""
    numbers = [int(part) for part in re.findall(r"\d+", version)]
    padded = (numbers + [0, 0, 0])[:3]
    return (padded[0], padded[1], padded[2])


def _walk_files(root: Path) -> list[Path]:
    """List the files under a model root, tolerating missing/unreadable roots."""
    if not root.is_dir():
        return []
    try:
        return [path for path in root.rglob("*") if path.is_file()]
    except OSError:
        return []


def _roots_text(roots: Sequence[Path]) -> str:
    if not roots:
        return "(no model roots configured)"
    return ", ".join(str(root) for root in roots)


def _missing_message(label: str, expected: str, roots: Sequence[Path]) -> str:
    return f"Missing {label} '{expected}' in model roots: {_roots_text(roots)}"


def _find_exact(
    basename: str, roots: Sequence[Path], files_by_root: dict[Path, list[Path]]
) -> Path | None:
    """Return the first file whose basename matches, searching roots in order."""
    target = basename.lower()
    for root in roots:
        for path in files_by_root[root]:
            if path.name.lower() == target:
                return path
    return None


def _find_variant_file(
    tokens: Sequence[str],
    suffix: str,
    roots: Sequence[Path],
    files_by_root: dict[Path, list[Path]],
) -> Path | None:
    """Return the first complete file for one quantization variant.

    The basename must contain every token and end with the quantization's
    extension. Partial downloads (``*.part``) are ignored because they cannot
    be loaded.
    """
    lowered_tokens = tuple(token.lower() for token in tokens)
    lowered_suffix = suffix.lower()
    for root in roots:
        for path in files_by_root[root]:
            lowered_name = path.name.lower()
            if lowered_name.endswith(".part"):
                continue
            if not lowered_name.endswith(lowered_suffix):
                continue
            if all(token in lowered_name for token in lowered_tokens):
                return path
    return None


def _model_check(
    found: Path | None, label: str, expected: str, roots: Sequence[Path]
) -> dict[str, object]:
    if found is not None:
        return {
            "ok": True,
            "path": str(found),
            "detail": f"Found {label}: {found}",
        }
    return {
        "ok": False,
        "path": None,
        "detail": _missing_message(label, expected, roots),
    }


def check_hyperflow_readiness(
    comfyui_root: str | Path,
    model_roots: Sequence[str | Path],
    *,
    server_running: bool,
) -> dict[str, object]:
    """Check whether the local ComfyUI + HyperFlow stack is ready to generate.

    Args:
        comfyui_root: ComfyUI installation root containing
            ``comfyui_version.py`` and ``custom_nodes/``.
        model_roots: Directories searched recursively for model files.
        server_running: Whether the ComfyUI server is currently reachable.
            The caller probes the server; this function makes no network calls.

    Returns:
        ``{"ready", "comfyui_version", "checks", "blockers", "warnings",
        "ready_variants", "variants"}``. ``variants`` maps each quantization
        (``"gguf"``, ``"int8"``) to ``{"ready", "fl2va", "ref2va", "blockers"}``;
        ``ready_variants`` lists the quantizations whose checkpoints are all
        present. The top-level ``ready`` is true only when the shared stack is
        healthy and at least one variant is complete. Top-level ``blockers``
        include the missing checkpoints only when no variant is complete —
        otherwise the per-variant ``blockers`` carry them. Warnings never
        prevent readiness.
    """
    comfy_root = Path(comfyui_root)
    roots = _normalise_roots(model_roots)

    checks: dict[str, dict[str, object]] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    version_file = comfy_root / "comfyui_version.py"
    version = _read_version(version_file)
    if version is None:
        version_ok = False
        version_detail = (
            f"No __version__ found in {version_file} "
            f"(required ComfyUI >= {MIN_COMFYUI_VERSION_TEXT})"
        )
        blockers.append(
            f"Missing ComfyUI version in {version_file}; "
            f"required >= {MIN_COMFYUI_VERSION_TEXT}"
        )
    else:
        version_ok = _version_tuple(version) >= MIN_COMFYUI_VERSION
        if version_ok:
            version_detail = (
                f"ComfyUI {version} satisfies >= {MIN_COMFYUI_VERSION_TEXT}"
            )
        else:
            version_detail = (
                f"ComfyUI {version} is older than the required "
                f"{MIN_COMFYUI_VERSION_TEXT}"
            )
            blockers.append(
                f"ComfyUI {version} is older than required "
                f"{MIN_COMFYUI_VERSION_TEXT} (searched {version_file})"
            )
    checks["comfyui_version"] = {
        "ok": version_ok,
        "path": str(version_file) if version_file.is_file() else None,
        "detail": version_detail,
    }

    custom_nodes = comfy_root / "custom_nodes"
    for node_pack in REQUIRED_CUSTOM_NODES:
        node_path = custom_nodes / node_pack
        node_ok = node_path.is_dir()
        checks[f"custom_node:{node_pack}"] = {
            "ok": node_ok,
            "path": str(node_path) if node_ok else None,
            "detail": (
                f"Custom node pack installed: {node_path}"
                if node_ok
                else f"Missing custom node pack '{node_pack}' "
                f"(searched {custom_nodes})"
            ),
        }
        if not node_ok:
            blockers.append(
                f"Missing custom node pack '{node_pack}' under {custom_nodes}"
            )

    checks["server_running"] = {
        "ok": bool(server_running),
        "path": None,
        "detail": (
            "ComfyUI server is running"
            if server_running
            else "ComfyUI server is not running"
        ),
    }
    if not server_running:
        blockers.append(
            "ComfyUI server is not running; start ComfyUI before local "
            "HyperFlow generation"
        )

    files_by_root = {root: _walk_files(root) for root in roots}

    for check_name, label, basename in REQUIRED_MODELS:
        found = _find_exact(basename, roots, files_by_root)
        checks[check_name] = _model_check(found, label, basename, roots)
        if found is None:
            blockers.append(_missing_message(label, basename, roots))

    variants: dict[str, dict[str, object]] = {}
    ready_variants: list[str] = []
    incomplete_variant_blockers: list[str] = []
    for variant_name, variant_checks in VARIANT_CHECKPOINTS.items():
        variant_paths: dict[str, str | None] = {"fl2va": None, "ref2va": None}
        variant_blockers: list[str] = []
        for checkpoint_key, label, pattern, tokens in variant_checks:
            found = _find_variant_file(
                tokens, VARIANT_SUFFIX[variant_name], roots, files_by_root
            )
            checks[f"hyperflow_{variant_name}_{checkpoint_key}_checkpoint"] = (
                _model_check(found, label, pattern, roots)
            )
            if found is None:
                variant_blockers.append(_missing_message(label, pattern, roots))
            else:
                variant_paths[checkpoint_key] = str(found)
        variant_ready = all(path is not None for path in variant_paths.values())
        variants[variant_name] = {
            "ready": variant_ready,
            "fl2va": variant_paths["fl2va"],
            "ref2va": variant_paths["ref2va"],
            "blockers": variant_blockers,
        }
        if variant_ready:
            ready_variants.append(variant_name)
        else:
            incomplete_variant_blockers.extend(variant_blockers)

    if not ready_variants:
        blockers.extend(incomplete_variant_blockers)

    sol_vae = _find_exact(SOL_VAE_NAME, roots, files_by_root)
    checks[SOL_VAE_CHECK] = _model_check(sol_vae, "sol VAE", SOL_VAE_NAME, roots)
    if sol_vae is None:
        warnings.append(
            f"Optional sol VAE '{SOL_VAE_NAME}' not found in model roots: "
            f"{_roots_text(roots)}; only the fast INT8 workflow needs it"
        )

    return {
        "ready": not blockers,
        "comfyui_version": version,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "ready_variants": ready_variants,
        "variants": variants,
    }
