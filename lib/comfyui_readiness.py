"""Shared filesystem-only helpers for ComfyUI readiness checks.

Both the HyperFlow checker (:mod:`lib.local_video_readiness`) and the local
post-enhancement checker (:mod:`lib.local_enhancement_readiness`) inspect the
same ComfyUI installation: the version file, ``custom_nodes`` packs, and the
configured model roots. This module holds those shared primitives so the two
checkers stay consistent. Nothing here touches the network.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

MIN_COMFYUI_VERSION = (0, 43, 0)
MIN_COMFYUI_VERSION_TEXT = "0.43.0"

_VERSION_PATTERN = re.compile(r'__version__\s*=\s*"([^"]+)"')


def normalise_roots(model_roots: Sequence[str | Path] | str | Path) -> list[Path]:
    """Accept one root or a sequence of roots and return a list of paths."""
    if isinstance(model_roots, (str, Path)):
        return [Path(model_roots)]
    return [Path(root) for root in model_roots]


def read_comfyui_version(version_file: Path) -> str | None:
    """Return ``__version__`` from a ComfyUI version file, or None."""
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _VERSION_PATTERN.search(text)
    return match.group(1) if match else None


def version_tuple(version: str) -> tuple[int, int, int]:
    """Turn a dotted version into three comparable integers."""
    numbers = [int(part) for part in re.findall(r"\d+", version)]
    padded = (numbers + [0, 0, 0])[:3]
    return (padded[0], padded[1], padded[2])


def walk_files(root: Path) -> list[Path]:
    """List the files under a model root, tolerating missing/unreadable roots."""
    if not root.is_dir():
        return []
    try:
        return [path for path in root.rglob("*") if path.is_file()]
    except OSError:
        return []


def roots_text(roots: Sequence[Path]) -> str:
    if not roots:
        return "(no model roots configured)"
    return ", ".join(str(root) for root in roots)


def missing_message(label: str, expected: str, roots: Sequence[Path]) -> str:
    return f"Missing {label} '{expected}' in model roots: {roots_text(roots)}"


def find_exact_file(
    basename: str, roots: Sequence[Path], files_by_root: dict[Path, list[Path]]
) -> Path | None:
    """Return the first file whose basename matches, searching roots in order."""
    target = basename.lower()
    for root in roots:
        for path in files_by_root[root]:
            if path.name.lower() == target:
                return path
    return None


def model_check(
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
        "detail": missing_message(label, expected, roots),
    }
