import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hell_grind_prompt_index.py"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(source: Path, output: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--source", str(source), "--output", str(output), *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_indexes_source_and_chinese_from_sideloaded_zh_md(tmp_path):
    source = tmp_path / "archive"
    prompts = source / "folders" / "Hell Grind" / "Scene 73.6" / "prompts"
    _write(
        prompts / "00001_1fcb1500.zh.md",
        """# prompt 对照

## 元数据
- job_set_id: 1fcb1500-64d0-4646-bde5-1e7fcea2a8e4
- job_type: seedance_2_0
- source_path: folders/Hell Grind/Scene 73.6/prompts/00001.txt
- folder_official_name: Scene 73.6
- translation_status: draft
- glossary_version: v0.1

## 原文 (source)

A boy tackles another boy into the grass.

## 中文对照 (zh)

一个男孩把另一个男孩扑进草地里。
""",
    )
    # An empty container must not become a prompt record.
    _write(
        prompts / "00002_empty.zh.md",
        """# prompt 对照

## 元数据
- job_set_id: empty
- job_type: seedance_2_0
- folder_official_name: Scene 73.6
- translation_status: draft

## 原文 (source)

## 中文对照 (zh)
""",
    )
    (prompts / "output.mp4").write_bytes(b"media")

    output = tmp_path / "index" / "prompts.jsonl"
    result = _run(source, output)

    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["scene"] == "Scene 73.6"
    assert record["job_set_id"] == "1fcb1500-64d0-4646-bde5-1e7fcea2a8e4"
    assert record["job_type"] == "seedance_2_0"
    assert record["prompt_path"] == "folders/Hell Grind/Scene 73.6/prompts/00001.txt"
    assert record["translation_status"] == "draft"
    assert record["prompt"] == "A boy tackles another boy into the grass."
    assert record["prompt_zh"] == "一个男孩把另一个男孩扑进草地里。"
    assert record["prompt_chars"] == len(record["prompt"])
    assert record["zh_path"].endswith("00001_1fcb1500.zh.md")
    assert "output.mp4" not in output.read_text(encoding="utf-8")
    assert not (tmp_path / "index" / "output.mp4").exists()


def test_limit_and_missing_metadata_are_safe(tmp_path):
    source = tmp_path / "archive"
    prompts = source / "folders" / "Hell Grind" / "Scene 1" / "prompts"
    _write(
        prompts / "00001_missing.zh.md",
        """# prompt 对照

## 原文 (source)

A prompt without metadata.

## 中文对照 (zh)

没有元数据的提示词。
""",
    )
    _write(
        prompts / "00002_second.zh.md",
        """# prompt 对照

## 元数据
- job_set_id: second
- job_type: nano_banana_2
- folder_official_name: Scene 1

## 原文 (source)

A second prompt.

## 中文对照 (zh)

第二条提示词。
""",
    )

    output = tmp_path / "out.jsonl"
    result = _run(source, output, "--limit", "1")

    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["scene"] == "Scene 1"
    assert record["prompt"] == "A prompt without metadata."
    assert record["prompt_path"] == ""
    assert record["job_set_id"] == ""
