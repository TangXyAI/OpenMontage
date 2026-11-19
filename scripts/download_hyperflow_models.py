#!/usr/bin/env python3
"""Download the HyperFlow H3 weights from ModelScope.

ModelScope is the primary source for these large files. The script only
downloads; it never moves or renames anything. After a real run it prints the
move destinations so the operator can place the files where ComfyUI expects
them.

Examples:
    python scripts/download_hyperflow_models.py --variant gguf --dry-run
    python scripts/download_hyperflow_models.py --variant gguf --accept-license
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_DEST = "G:/ComfyUI/Shared/downloads/hyperflow"
DIFFUSION_MODELS_DIR = "G:/ComfyUI/Shared/models/diffusion_models"
VAE_DIR = "G:/ComfyUI/Shared/models/vae"

# (ModelScope repo, path inside the repo, size in GB) — docs/hell-grind-integration.md 4.7.1.
SOURCES = {
    "gguf": [
        (
            "VideoRebirthAI/hyperflow-h3-flash",
            "fl2va_gguf/minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf",
            9.05,
        ),
        (
            "VideoRebirthAI/hyperflow-h3-flash",
            "ref2va_gguf/minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf",
            9.22,
        ),
        (
            "Comfy-Org/MiniMax-H3",
            "vae/minimax_h3_sol_vae_int8_convrot.safetensors",
            1.99,
        ),
    ],
    "int8": [
        (
            "VideoRebirthAI/hyperflow-h3-flash",
            "fl2va_int8_convrot_comfyui/minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors",
            16.01,
        ),
        (
            "VideoRebirthAI/hyperflow-h3-flash",
            "ref2va_int8_convrot_comfyui/minimax_h3_ref2va_hyperflow_flash_14b-int8_convrot.safetensors",
            16.43,
        ),
        (
            "Comfy-Org/MiniMax-H3",
            "vae/minimax_h3_sol_vae_int8_convrot.safetensors",
            1.99,
        ),
    ],
}


def download_command(repo: str, relpath: str, dest: str) -> list[str]:
    """Return the ``modelscope download`` argument list for one file."""
    return [
        "modelscope",
        "download",
        "--model",
        repo,
        "--include",
        relpath,
        "--local_dir",
        dest,
    ]


def move_destination(relpath: str) -> str:
    """Return the ComfyUI directory the downloaded file belongs in."""
    if relpath.startswith("vae/") or "/vae/" in relpath:
        return VAE_DIR
    return DIFFUSION_MODELS_DIR


def format_command(command: list[str]) -> str:
    """Render a command for humans, quoting the include glob like the docs."""
    if "--include" not in command:
        return " ".join(command)
    include_index = command.index("--include") + 1
    return " ".join(
        f"'{arg}'" if index == include_index else arg
        for index, arg in enumerate(command)
    )


def print_plan(variant: str, dest: str) -> None:
    files = SOURCES[variant]
    print(f"ModelScope download plan (variant={variant}, dest={dest}):")
    total = 0.0
    for repo, relpath, size_gb in files:
        total += size_gb
        command = format_command(download_command(repo, relpath, dest))
        print(f"{command}  [{size_gb:.2f} GB]")
    print(f"Total: {total:.2f} GB")
    print()
    print("Move destinations (this script never moves or renames files):")
    for _repo, relpath, _size_gb in files:
        source = Path(dest) / relpath
        target = Path(move_destination(relpath)) / Path(relpath).name
        print(f"  {source} -> {target}")


def modelscope_executable() -> list[str]:
    """Prefer the installed console script; fall back to ``python -m modelscope``."""
    found = shutil.which("modelscope")
    if found:
        return [found]
    sibling = Path(sys.executable).with_name("modelscope.exe" if os.name == "nt" else "modelscope")
    if sibling.exists():
        return [str(sibling)]
    return [sys.executable, "-m", "modelscope"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download the HyperFlow H3 weights from ModelScope."
    )
    parser.add_argument(
        "--variant",
        choices=sorted(SOURCES),
        default="gguf",
        help="Weight variant to download (default: gguf).",
    )
    parser.add_argument(
        "--dest",
        default=DEFAULT_DEST,
        help=f"ModelScope local_dir for downloads (default: {DEFAULT_DEST}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands and sizes without downloading anything.",
    )
    parser.add_argument(
        "--accept-license",
        action="store_true",
        help="Accept the MiniMax H3 Community License; required for a real download.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        print_plan(args.variant, args.dest)
        return 0

    if not args.accept_license:
        print(
            "Error: pass --accept-license to accept the MiniMax H3 Community License.",
            file=sys.stderr,
        )
        return 2

    try:
        import modelscope  # noqa: F401
    except ImportError:
        print("Error: modelscope is not installed. Run: pip install modelscope", file=sys.stderr)
        return 2

    executable = modelscope_executable()
    files = SOURCES[args.variant]
    print(f"Downloading HyperFlow {args.variant} weights to {args.dest} ...")
    for repo, relpath, size_gb in files:
        command = [*executable, *download_command(repo, relpath, args.dest)[1:]]
        print(f"[{size_gb:.2f} GB] {format_command(command)}")
        result = subprocess.run(command)
        if result.returncode != 0:
            print(
                f"Error: download failed for {repo}/{relpath} (exit {result.returncode}).",
                file=sys.stderr,
            )
            return 1

    print()
    print("Download complete. Move each file to its ComfyUI directory:")
    for _repo, relpath, _size_gb in files:
        source = Path(args.dest) / relpath
        target = Path(move_destination(relpath)) / Path(relpath).name
        print(f"  {source} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
