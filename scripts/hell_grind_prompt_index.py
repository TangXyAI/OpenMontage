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
import os
import re
import sys
from pathlib import Path

_META_RE = re.compile(r"^-\s+([A-Za-z_]+):\s*(.*)$")
_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
_SOURCE_MARK_RE = re.compile(r"^\*\*source:\*\*\s*$", re.IGNORECASE)
_ZH_MARK_RE = re.compile(r"^\*\*zh:\*\*\s*$", re.IGNORECASE)


def _clean_section(text: str) -> str:
    """Strip a leading and/or trailing Markdown code fence and structural tail."""
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip() in {"```", "---", ""}:
        lines.pop()
    return "\n".join(lines).strip()


def _split_combined(body: str) -> tuple[str, str]:
    """Split a `## 原文 (source) · 中文对照 (zh)` block into source and Chinese."""
    source: list[str] = []
    chinese: list[str] = []
    mode: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        if _SOURCE_MARK_RE.match(stripped):
            mode = "source"
            continue
        if _ZH_MARK_RE.match(stripped):
            mode = "zh"
            continue
        if mode == "source":
            source.append(line)
        elif mode == "zh":
            chinese.append(line)
    if not source and not chinese:
        return _clean_section(body), ""
    return _clean_section("\n".join(source)), _clean_section("\n".join(chinese))


def parse_prompt_markdown(text: str) -> tuple[dict[str, str], str, str]:
    """Return ``(metadata, source_text, chinese_text)`` from one ``.zh.md``."""
    metadata: dict[str, str] = {}
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current == "COMBINED":
            source, chinese = _split_combined("\n".join(buffer))
            sections["原文"] = source
            sections["中文对照"] = chinese
        elif current is not None:
            sections[current] = _clean_section("\n".join(buffer))
        current, buffer = None, []

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            title = heading.group(1)
            if title.startswith(("备注", "段落对齐备注", "参考资产", "元数据头")):
                # Translator notes and sidecar sections terminate the prompt;
                # they must never flow into prompt or prompt_zh.
                flush()
                continue
            known = (
                title == "元数据"
                or title.startswith("原文")
                or title.startswith("中文对照")
            )
            if known:
                flush()
                combined = title.startswith("原文") and "中文对照" in title
                current = "COMBINED" if combined else title
                continue
            # An unknown `## ` heading (e.g. GEOMETRY) is part of the current
            # prompt text, not a new metadata/source section; keep it so the
            # prompt is not cut.
        if current == "元数据":
            match = _META_RE.match(line.strip())
            if match:
                key, raw = match.group(1), match.group(2).strip()
                if key in {"job_set_id", "job_type", "source_path"}:
                    token = re.search(r"`([^`]+)`", raw)
                    value = token.group(1).strip() if token else raw.strip("`").strip()
                else:
                    value = raw
                    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
                        value = value[1:-1].strip()
                metadata[key] = value
        elif current is not None:
            buffer.append(line)
    flush()

    source = next((value for key, value in sections.items() if key.startswith("原文")), "")
    chinese = next((value for key, value in sections.items() if key.startswith("中文对照")), "")
    return metadata, source, chinese


def build_record(path: Path, source_root: Path) -> dict[str, object] | None:
    metadata, prompt, prompt_zh = parse_prompt_markdown(
        path.read_text(encoding="utf-8", errors="replace")
    )
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


DEFAULT_OUTPUT = "reference/hell-grind/prompts.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=r"D:\AI\higgsfield-hell-grind-opensource",
        help="Hell-Grind archive root (default: the local mirror)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output JSONL path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Write at most N records (0 = all)",
    )
    args = parser.parse_args(argv)

    if args.limit < 0:
        print("error: --limit must be >= 0", file=sys.stderr)
        return 2
    if args.limit and Path(args.output) == Path(DEFAULT_OUTPUT):
        print(
            "error: --limit requires an explicit --output so a preview cannot "
            "overwrite the full index",
            file=sys.stderr,
        )
        return 2

    source_root = Path(args.source).resolve()
    if not source_root.is_dir():
        print(f"error: source directory not found: {source_root}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")

    seen = 0
    skipped = 0
    written = 0
    errors = 0
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for path in iter_prompt_files(source_root):
                seen += 1
                try:
                    record = build_record(path, source_root)
                except Exception as exc:  # keep one bad file from aborting the corpus
                    errors += 1
                    print(f"warning: skipped {path}: {exc}", file=sys.stderr)
                    continue
                if record is None:
                    skipped += 1
                    continue
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                if args.limit and written >= args.limit:
                    break
        os.replace(temp, output)
    except Exception:
        if temp.exists():
            temp.unlink()
        raise

    print(
        f"indexed {written} prompts ({seen} examined, {skipped} empty, "
        f"{errors} errors) -> {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
