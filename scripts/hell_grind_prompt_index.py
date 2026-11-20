#!/usr/bin/env python3
"""Build a JSONL index of Hell-Grind prompts from sideloaded ``*.zh.md`` files.

The archive keeps the source prompt and its Chinese translation side by side:

    folders/<project>/<scene>/prompts/00001_<job_set_id>.txt
    folders/<project>/<scene>/prompts/00001_<job_set_id>.zh.md

The local mirror may contain only the ``.zh.md`` files. This script extracts the
source text, the Chinese text, and the job metadata from each one, and writes a
single JSONL file for few-shot retrieval. It never copies media or touches the
archive.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_META_RE = re.compile(r"^-\s+([A-Za-z_]+):\s*(.*)$")
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def _clean_section(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    return text


def parse_prompt_markdown(text: str) -> tuple[dict[str, str], str, str]:
    """Return ``(metadata, source_text, chinese_text)`` from one ``.zh.md``."""
    metadata: dict[str, str] = {}
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is not None:
            sections[current] = _clean_section("\n".join(buffer))
        current, buffer = None, []

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            current = heading.group(1)
            continue
        if current == "元数据":
            match = _META_RE.match(line.strip())
            if match:
                metadata[match.group(1)] = match.group(2).strip()
        elif current is not None:
            buffer.append(line)
    flush()

    source = next((value for key, value in sections.items() if key.startswith("原文")), "")
    chinese = next((value for key, value in sections.items() if key.startswith("中文对照")), "")
    return metadata, source, chinese


def build_record(path: Path, source_root: Path) -> dict[str, object] | None:
    metadata, prompt, prompt_zh = parse_prompt_markdown(path.read_text(encoding="utf-8"))
    if not prompt and not prompt_zh:
        return None
    scene = metadata.get("folder_official_name") or path.parent.parent.name
    return {
        "scene": scene,
        "prompt_path": metadata.get("source_path", ""),
        "zh_path": path.relative_to(source_root).as_posix(),
        "job_set_id": metadata.get("job_set_id", ""),
        "job_type": metadata.get("job_type", ""),
        "translation_status": metadata.get("translation_status", ""),
        "prompt": prompt,
        "prompt_zh": prompt_zh,
        "prompt_chars": len(prompt),
    }


def iter_prompt_files(source_root: Path):
    for path in sorted(source_root.rglob("*.zh.md")):
        if path.parent.name != "prompts":
            continue
        yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=r"D:\AI\higgsfield-hell-grind-opensource",
        help="Hell-Grind archive root (default: the local mirror)",
    )
    parser.add_argument(
        "--output",
        default="reference/hell-grind/prompts.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Write at most N records (0 = all)",
    )
    args = parser.parse_args(argv)

    source_root = Path(args.source).resolve()
    if not source_root.is_dir():
        print(f"error: source directory not found: {source_root}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    seen = 0
    skipped = 0
    written = 0
    with output.open("w", encoding="utf-8") as handle:
        for path in iter_prompt_files(source_root):
            seen += 1
            record = build_record(path, source_root)
            if record is None:
                skipped += 1
                continue
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
            if args.limit and written >= args.limit:
                break

    print(f"indexed {written} prompts ({seen} examined, {skipped} empty) -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
