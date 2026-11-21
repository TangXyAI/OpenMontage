# 视频后期增强接入流水线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 H3-FaceRefine 与 SeedVR2 3B FP8 两条本地后期增强路线接入 `cinematic` 流水线的 `assets` 阶段，由用户选择、记录决策，并把增强结果与溯源写回资产清单。

**Architecture:** 新增独立 `comfyui_enhance` 工具（复用 `tools/_comfyui/client.py`），内置两个 API 格式工作流；新增离线就绪检查与增强菜单；增强通过替换被选 take 的媒体路径实现，保持 `narrative_assets` 选片一致；`cinematic.yaml` 增加 `enhancement_selection` 子门禁，导演技能负责菜单与决策。

**Tech Stack:** Python 3.11（`.venv`）、ComfyUI REST API、ffmpeg/ffprobe、pytest、JSON Schema、YAML pipeline manifest。

**Spec:** `docs/superpowers/specs/2026-11-21-video-enhancement-design.md`

## Global Constraints

- 平台：Windows 10；所有 Python 命令使用 `.venv/Scripts/python.exe`。
- Rule Zero：Python 只做工具与持久化；菜单、取舍、审批在指令层。
- 只支持本地 ComfyUI；禁止云端增强、禁止自动回退到 Real-ESRGAN / GFPGAN / FFmpeg 滤镜。
- 所有生成产物必须写入 `projects/<project_id>/` 下的显式路径。
- 工具类名 PascalCase 无 `Tool` 后缀；工具放在 `tools/` 下会被 registry 自动发现。
- `decision_log` 与 `asset_manifest` 的 schema 都是 `additionalProperties: false`，新增字段必须同步改 schema。
- `face_refine` 必须恰好 2 张参考图；`video_upscale` 不需要参考图。
- `face_refine` 的 `23.frame_rate` 必须绑定源 ffprobe 帧率，禁止硬编码 24。
- 决策类别固定 `enhancement_selection`，决策 subject 固定 `Post-enhancement route`。
- 不新增 `video_compose` 的渲染路径；`render_runtime` 不变。

## Review Focus

- 非 24 fps 源片进入 FaceRefine → 输出帧率与时长必须保持不变（Task 6 的帧率绑定测试）。
- 无音轨源片 → 输出不得凭空多出音轨，也不得丢失源音轨（Task 6 的流数量校验测试）。
- 增强后用户重新选片或编辑计划过期 → `video_compose` 必须拒绝，而不是渲染旧路径（Task 4 的守卫回归测试）。
- ComfyUI 未启动 / 缺自定义节点 / 缺模型 → 菜单显示 unavailable 且带 blocker，工具不得静默回退（Task 2 与 Task 7 的测试）。
- `face_refine` 只给 1 张参考图或输出路径不在项目内 → 必须明确报错，不能复制图片或写到项目外（Task 5 的校验测试）。

---

## File Structure

- `schemas/artifacts/decision_log.schema.json` — 增加 `enhancement_selection` 类别。
- `schemas/artifacts/asset_manifest.schema.json` — 增加可选 `enhancement` 对象。
- `lib/comfyui_readiness.py`（新建）— 从 `local_video_readiness.py` 抽出的共享文件系统检查助手。
- `lib/local_video_readiness.py` — 改为引用共享助手，行为不变。
- `lib/local_enhancement_readiness.py`（新建）— 两条增强路线的离线就绪检查。
- `lib/narrative_assets.py` — 新增 `apply_enhancement`，`asset_manifest()` 输出 `enhancement`。
- `lib/enhancement_selection.py`（新建）— 增强菜单、决策写入与校验。
- `tools/_comfyui/client.py` — 新增通用输入文件上传方法。
- `tools/_comfyui/workflows/enhance_face_refine_h3_api.json`（新建）
- `tools/_comfyui/workflows/enhance_seedvr2_3b_api.json`（新建）
- `tools/_comfyui/workflows/ENHANCE_PROVENANCE.md`（新建）
- `tools/enhancement/comfyui_enhance.py`（新建）— 增强工具。
- `.agents/skills/video-enhancement/SKILL.md`（新建）— Layer 3。
- `skills/creative/video-enhancement.md`（新建）— Layer 2。
- `pipeline_defs/cinematic.yaml` — assets 子门禁与工具清单。
- `skills/pipelines/cinematic/{asset,edit,compose,proposal}-director.md` — 阶段指令。
- `skills/creative/video-model-selection.md` — 交叉引用。
- 测试：`tests/contracts/test_video_enhancement_schemas.py`、`tests/contracts/test_enhancement_workflows.py`、`tests/contracts/test_video_enhancement_integration.py`、`tests/lib/test_local_enhancement_readiness.py`、`tests/lib/test_narrative_enhancement.py`、`tests/lib/test_enhancement_selection.py`、`tests/tools/test_comfyui_enhance_bindings.py`、`tests/tools/test_comfyui_enhance_execute.py`、`tests/tools/test_comfyui_client_upload.py`。

---

### Task 1: Schema Updates

**Files:**
- Modify: `schemas/artifacts/decision_log.schema.json`
- Modify: `schemas/artifacts/asset_manifest.schema.json`
- Test: `tests/contracts/test_video_enhancement_schemas.py`

**Interfaces:**
- Produces: `decision_log.decisions[].category` 接受 `"enhancement_selection"`；`asset_manifest.assets[]` 接受可选 `enhancement` 对象，字段为 `operation`（`face_refine|video_upscale`）、`model`、`source_path`、`parameters`、`workflow_hash_sha256`。

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / "artifacts" / f"{name}.schema.json").read_text(encoding="utf-8"))


def _decision(category: str) -> dict:
    return {
        "version": "1.0",
        "project_id": "p",
        "decisions": [{
            "decision_id": "d-001",
            "stage": "assets",
            "category": category,
            "subject": "Post-enhancement route",
            "options_considered": [{
                "option_id": "seedvr2_upscale", "label": "SeedVR2", "score": 1.0,
                "reason": "best detail",
            }],
            "selected": "seedvr2_upscale",
            "reason": "approved",
        }],
    }


def _manifest(enhancement: dict | None) -> dict:
    asset = {
        "id": "take:s1:take1", "type": "video", "path": "assets/video/s1-take1.mp4",
        "source_tool": "comfyui_video", "scene_id": "s1",
    }
    if enhancement is not None:
        asset["enhancement"] = enhancement
    return {"version": "1.0", "assets": [asset]}


def test_decision_log_accepts_enhancement_selection():
    jsonschema.validate(_decision("enhancement_selection"), _schema("decision_log"))


def test_decision_log_still_rejects_unknown_category():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_decision("enhancement"), _schema("decision_log"))


def test_asset_manifest_accepts_enhancement_object():
    jsonschema.validate(_manifest({
        "operation": "video_upscale",
        "model": "SeedVR2 3B FP8",
        "source_path": "assets/video/s1-take1.mp4",
        "parameters": {"resolution": 1080},
        "workflow_hash_sha256": "abc",
    }), _schema("asset_manifest"))


def test_asset_manifest_rejects_unknown_enhancement_key():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_manifest({
            "operation": "face_refine", "model": "H3-FaceRefine",
            "source_path": "assets/video/s1-take1.mp4", "unexpected": 1,
        }), _schema("asset_manifest"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_video_enhancement_schemas.py -v`
Expected: FAIL — `enhancement_selection` not in enum; `enhancement` not allowed by `additionalProperties: false`.

- [ ] **Step 3: Edit the schemas**

- `decision_log.schema.json`：在 `category.enum` 末尾加入 `"enhancement_selection"`。
- `asset_manifest.schema.json`：在 asset item 的 `properties` 中加入：

```json
"enhancement": {
  "type": "object",
  "required": ["operation", "model", "source_path"],
  "properties": {
    "operation": {"enum": ["face_refine", "video_upscale"]},
    "model": {"type": "string"},
    "source_path": {"type": "string"},
    "parameters": {"type": "object"},
    "workflow_hash_sha256": {"type": "string"}
  },
  "additionalProperties": false
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_video_enhancement_schemas.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add schemas/artifacts/decision_log.schema.json schemas/artifacts/asset_manifest.schema.json tests/contracts/test_video_enhancement_schemas.py
git commit -m "feat(schema): 允许增强决策与资产溯源字段"
```

---

### Task 2: Shared Readiness Helpers and Enhancement Readiness

**Files:**
- Create: `lib/comfyui_readiness.py`
- Modify: `lib/local_video_readiness.py`
- Create: `lib/local_enhancement_readiness.py`
- Test: `tests/lib/test_local_enhancement_readiness.py`

**Interfaces:**
- Produces: `check_enhancement_readiness(comfyui_root, model_roots, *, server_running, models=None) -> dict`，返回 `{"ready", "server_running", "comfyui_version", "checks", "blockers", "warnings", "routes", "ready_routes"}`；`routes["face_refine"]`/`routes["video_upscale"]` 含 `{"ready", "blockers", "warnings", "models"}`。
- Consumes: `lib/comfyui_readiness.py` 的公开助手：`normalise_roots`、`read_comfyui_version`、`version_tuple`、`walk_files`、`find_exact_file`、`roots_text`、`model_check`、`MIN_COMFYUI_VERSION`。

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_local_enhancement_readiness.py -v`
Expected: FAIL — `lib.local_enhancement_readiness` does not exist.

- [ ] **Step 3: Extract shared helpers, then implement the checker**

- 新建 `lib/comfyui_readiness.py`，把 `local_video_readiness.py` 中的 `_normalise_roots`、`_read_version`、`_version_tuple`、`_walk_files`、`_roots_text`、`_find_exact`、`_model_check`、`MIN_COMFYUI_VERSION`、`MIN_COMFYUI_VERSION_TEXT` 改成公开名（去掉前导下划线），逻辑逐字保留。
- 在 `local_video_readiness.py` 顶部改为 `from lib.comfyui_readiness import ...`，删除本地重复定义；`check_hyperflow_readiness` 行为不变。
- 新建 `lib/local_enhancement_readiness.py`：
  - `DEFAULT_MODELS = {"unet": ..., "clip": ..., "vae_video": ..., "vae_audio": ..., "lora": r"MiniMax-H3\加速\PikaFlex-Turbo-8步高清多模态参考视频加速.safetensors", "detector": "face_yolov8n.pt", "seedvr2_dit": "seedvr2_ema_3b_fp8_e4m3fn.safetensors", "seedvr2_vae": "ema_vae_fp16.safetensors"}`
  - `REQUIRED_NODES = {"face_refine": ("ComfyUI-H3-FaceRefine", "comfyui-videohelpersuite"), "video_upscale": ("seedvr2_videoupscaler",)}`，目录匹配用 `casefold()`。
  - face_refine 模型缺失均为 blocker；`insightface` 目录/文件缺失为 warning。
  - SeedVR2 DiT 缺失为 warning（文案包含 `3.16`），VAE 缺失为 blocker。
  - 顶层 `blockers` 永远包含 `"ComfyUI server is not running"`（当 `server_running=False`）。
  - `ready = server_running and bool(ready_routes)`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_local_enhancement_readiness.py tests/lib/test_local_video_readiness.py -v`
Expected: 全部 passed（新 8 项 + 现有 HyperFlow 用例）。

- [ ] **Step 5: Commit**

```bash
git add lib/comfyui_readiness.py lib/local_video_readiness.py lib/local_enhancement_readiness.py tests/lib/test_local_enhancement_readiness.py
git commit -m "feat(enhancement): 增加本地后期增强就绪检查"
```

---

### Task 3: Bundle the Two Enhancement Workflows

**Files:**
- Create: `tools/_comfyui/workflows/enhance_face_refine_h3_api.json`
- Create: `tools/_comfyui/workflows/enhance_seedvr2_3b_api.json`
- Create: `tools/_comfyui/workflows/ENHANCE_PROVENANCE.md`
- Test: `tests/contracts/test_enhancement_workflows.py`

**Interfaces:**
- Produces: 两个 API 格式工作流，输出节点均为 `"23"`；`face_refine` 必需节点 `1,2,4,5,6,7,9,12,16,17,23,31,108,109`；`video_upscale` 必需节点 `10,13,14,21,22,23,24`。

- [ ] **Step 1: Write the failing test**

```python
import json
import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / "tools" / "_comfyui" / "workflows"


def _load(name: str) -> dict:
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def _assert_api_format(workflow: dict) -> None:
    assert workflow
    for node_id, node in workflow.items():
        assert isinstance(node, dict), node_id
        assert "class_type" in node, node_id
        assert isinstance(node.get("inputs"), dict), node_id


def test_face_refine_workflow_is_clean_api_format():
    workflow = _load("enhance_face_refine_h3_api.json")
    _assert_api_format(workflow)
    required = {"1", "2", "4", "5", "6", "7", "9", "12", "16", "17", "23", "31", "108", "109"}
    assert required <= set(workflow)
    assert workflow["1"]["inputs"]["video"] == ""
    assert workflow["6"]["inputs"]["image"] == ""
    assert workflow["7"]["inputs"]["image"] == ""
    assert workflow["23"]["inputs"]["filename_prefix"] == "om_enhance/face_refine"


def test_seedvr2_workflow_is_clean_api_format():
    workflow = _load("enhance_seedvr2_3b_api.json")
    _assert_api_format(workflow)
    required = {"10", "13", "14", "21", "22", "23", "24"}
    assert required <= set(workflow)
    assert workflow["21"]["inputs"]["file"] == ""
    assert workflow["23"]["inputs"]["filename_prefix"] == "om_enhance/seedvr2"


def test_workflows_have_no_machine_specific_paths():
    for name in ("enhance_face_refine_h3_api.json", "enhance_seedvr2_3b_api.json"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:[\\/]", text), name
        assert "_h3-api-export" not in text, name
        assert "smoke_" not in text, name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_enhancement_workflows.py -v`
Expected: FAIL — files do not exist.

- [ ] **Step 3: Generate the bundled workflows**

Running this one-off from the repository root (the experiment files are untracked but present on this machine):

```python
import json
from pathlib import Path

src = Path("projects/_h3-api-export")
dst = Path("tools/_comfyui/workflows")
dst.mkdir(parents=True, exist_ok=True)

face = json.loads((src / "face_refine_official.api.json").read_text(encoding="utf-8"))
face["1"]["inputs"]["video"] = ""
face["6"]["inputs"]["image"] = ""
face["7"]["inputs"]["image"] = ""
face["23"]["inputs"]["filename_prefix"] = "om_enhance/face_refine"
face["23"]["inputs"]["frame_rate"] = 24  # bound to the source fps at runtime
(dst / "enhance_face_refine_h3_api.json").write_text(
    json.dumps(face, ensure_ascii=False, indent=2), encoding="utf-8"
)

seed = json.loads((src / "seedvr2_test.api.json").read_text(encoding="utf-8"))
seed["21"]["inputs"]["file"] = ""
seed["23"]["inputs"]["filename_prefix"] = "om_enhance/seedvr2"
(dst / "enhance_seedvr2_3b_api.json").write_text(
    json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8"
)
```

写 `ENHANCE_PROVENANCE.md`，内容至少包含：来源（`ComfyUI-H3-FaceRefine` 的 `H3_Face_Refine_Auto_Select.json`、`seedvr2_videoupscaler` 的 `SeedVR2_HD_video_upscale.json`）、经 ComfyUI 前端导出 API 格式、本机补丁（源路径/参考图/输出前缀清空；FaceRefine 检测器与去噪乘数）、默认可覆盖的模型文件名、H3 与 SeedVR2 的许可提示、无权重入仓。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_enhancement_workflows.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/_comfyui/workflows/enhance_face_refine_h3_api.json tools/_comfyui/workflows/enhance_seedvr2_3b_api.json tools/_comfyui/workflows/ENHANCE_PROVENANCE.md tests/contracts/test_enhancement_workflows.py
git commit -m "feat(enhancement): 内置 FaceRefine 与 SeedVR2 工作流"
```

---

### Task 4: Narrative Asset Enhancement and Selection Guard

**Files:**
- Modify: `lib/narrative_assets.py`
- Test: `tests/lib/test_narrative_enhancement.py`

**Interfaces:**
- Produces: `NarrativeAssets.apply_enhancement(shot_id, take_id, path, *, duration_seconds, enhancement) -> None`；`asset_manifest()` 的 take 条目在存在增强时携带 `enhancement` 对象。
- Consumes: `NarrativeAssets` 现有 `_media`、`select_take`、`edit_decisions`。

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from lib.checkpoint import read_checkpoint, write_checkpoint
from lib.narrative_assets import NarrativeAssets
from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose


def _catalog(tmp_path: Path) -> NarrativeAssets:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    for name in ("a.mp4", "b.mp4"):
        (root / name).write_bytes(b"video")
    catalog = NarrativeAssets(root)
    catalog.add_take("s1", "take1", "a.mp4", 7.0)
    catalog.add_take("s1", "take2", "b.mp4", 7.0)
    catalog.select_take("s1", "take1")
    return catalog


def _enhancement(path: str = "assets/video/enhanced/s1-take1-upscale.mp4") -> dict:
    return {
        "operation": "video_upscale",
        "model": "SeedVR2 3B FP8",
        "source_path": "a.mp4",
        "parameters": {"resolution": 1080},
        "workflow_hash_sha256": "abc",
    }


def test_apply_enhancement_requires_selected_take(tmp_path):
    catalog = _catalog(tmp_path)
    enhanced = tmp_path / "project" / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    with pytest.raises(ValueError, match="selected"):
        catalog.apply_enhancement("s1", "take2", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())


def test_apply_enhancement_keeps_first_original_path(tmp_path):
    catalog = _catalog(tmp_path)
    enhanced = tmp_path / "project" / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    first = catalog.data["shots"]["s1"]["takes"]["take1"]["metadata"]["original_path"]
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    assert catalog.data["shots"]["s1"]["takes"]["take1"]["metadata"]["original_path"] == first
    assert first == "a.mp4"


def test_asset_manifest_exposes_enhancement(tmp_path):
    catalog = _catalog(tmp_path)
    enhanced = tmp_path / "project" / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    take = next(item for item in catalog.asset_manifest()["assets"] if item["type"] == "video")
    assert take["enhancement"]["operation"] == "video_upscale"


def test_guarded_compose_accepts_enhanced_selection(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    root = tmp_path / "project"
    enhanced = root / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s1"], "ffmpeg")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: ToolResult(success=True))
    result = tool.execute({
        "operation": "render", "project_dir": str(root),
        "edit_decisions": edit, "asset_manifest": manifest,
        "output_path": str(root / "out.mp4"),
    })
    assert result.success, result.error


def test_guarded_compose_rejects_stale_path_after_enhancement(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    root = tmp_path / "project"
    enhanced = root / "assets/video/enhanced/s1-take1-upscale.mp4"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    manifest = catalog.asset_manifest()
    edit = catalog.edit_decisions(["s1"], "ffmpeg")
    write_checkpoint(tmp_path, "project", "assets", "completed", {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
    write_checkpoint(tmp_path, "project", "edit", "completed", {"edit_decisions": edit})
    catalog.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.0, enhancement=_enhancement())
    tool = VideoCompose()
    monkeypatch.setattr(tool, "_pre_compose_validation", lambda *args: None)
    monkeypatch.setattr(tool, "_render_via_ffmpeg", lambda **kwargs: ToolResult(success=True))
    result = tool.execute({
        "operation": "render", "project_dir": str(root),
        "edit_decisions": edit, "asset_manifest": manifest,
        "output_path": str(root / "out.mp4"),
    })
    assert not result.success
    assert "does not match narrative selection" in result.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_narrative_enhancement.py -v`
Expected: FAIL — `apply_enhancement` does not exist.

- [ ] **Step 3: Implement**

- 在 `NarrativeAssets` 中加入：

```python
def apply_enhancement(self, shot_id: str, take_id: str, path: str, *, duration_seconds: float, enhancement: dict[str, Any]) -> None:
    shot = self.data["shots"].get(shot_id)
    if not shot or shot.get("selected") != take_id or take_id not in shot.get("takes", {}):
        raise ValueError(f"Enhancement requires the selected take: {shot_id}/{take_id}")
    if duration_seconds <= 0:
        raise ValueError("Enhanced take needs a positive duration")
    media = self._media(path)
    take = shot["takes"][take_id]
    metadata = take.setdefault("metadata", {})
    metadata.setdefault("original_path", take["path"])
    take["path"] = media
    take["duration_seconds"] = duration_seconds
    metadata["enhancement"] = dict(enhancement)
    self._save()
```

- 在 `asset_manifest()` 的 take 分支里，复制既有键之后加：

```python
if "enhancement" in take.get("metadata", {}):
    item["enhancement"] = take["metadata"]["enhancement"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_narrative_enhancement.py tests/contracts/test_narrative_edit_integration.py -v`
Expected: 新 5 项与现有叙事集成测试全部 passed。

- [ ] **Step 5: Commit**

```bash
git add lib/narrative_assets.py tests/lib/test_narrative_enhancement.py
git commit -m "feat(narrative): 增强结果写回被选 take 并保留选片一致性"
```

---

### Task 5: `comfyui_enhance` Contract and Workflow Binding

**Files:**
- Create: `tools/enhancement/comfyui_enhance.py`
- Test: `tests/tools/test_comfyui_enhance_bindings.py`

**Interfaces:**
- Produces: `ComfyUIEnhance.__init__(client=None)`；`ComfyUIEnhance._validate_inputs(inputs) -> str | None`；`ComfyUIEnhance._merged_models(inputs) -> dict[str, str]`；`ComfyUIEnhance._workflow_patches(operation, inputs, *, source_fps, source_name, ref_names, output_prefix) -> dict[str, dict[str, Any]]`。

- [ ] **Step 1: Write the failing test**

```python
import pytest

from tools.enhancement.comfyui_enhance import ComfyUIEnhance


def _tool(tmp_path):
    return ComfyUIEnhance(client=object())


def _face_inputs(tmp_path):
    refs = []
    for name in ("face.png", "wardrobe.png"):
        path = tmp_path / name
        path.write_bytes(b"img")
        refs.append(str(path))
    source = tmp_path / "take.mp4"
    source.write_bytes(b"video")
    project = tmp_path / "project"
    (project / "assets/video/enhanced").mkdir(parents=True)
    return {
        "operation": "face_refine",
        "input_path": str(source),
        "output_path": str(project / "assets/video/enhanced/s1-take1-face-refine.mp4"),
        "project_dir": str(project),
        "reference_image_paths": refs,
        "prompt": "subject_definitions: ...",
    }


def test_unknown_operation_is_rejected(tmp_path):
    inputs = _face_inputs(tmp_path) | {"operation": "sharpen"}
    assert "operation" in ComfyUIEnhance._validate_inputs(inputs)


def test_face_refine_requires_exactly_two_references(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["reference_image_paths"] = inputs["reference_image_paths"][:1]
    assert "two reference images" in ComfyUIEnhance._validate_inputs(inputs)


def test_face_refine_requires_prompt(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["prompt"] = ""
    assert "prompt" in ComfyUIEnhance._validate_inputs(inputs)


def test_output_must_stay_inside_project_dir(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["output_path"] = str(tmp_path / "outside.mp4")
    assert "project" in ComfyUIEnhance._validate_inputs(inputs)


def test_face_refine_binds_every_required_node(tmp_path):
    inputs = _face_inputs(tmp_path)
    patches = ComfyUIEnhance._workflow_patches(
        "face_refine", inputs,
        source_fps=25.0,
        source_name=str(tmp_path / "take.mp4"),
        ref_names=["face.png", "wardrobe.png"],
        output_prefix="om_enhance/face_refine",
    )
    assert patches["1"]["video"] == str(tmp_path / "take.mp4")
    assert patches["6"]["image"] == "face.png"
    assert patches["7"]["image"] == "wardrobe.png"
    assert patches["9"]["prompt"] == inputs["prompt"]
    assert patches["2"]["select"] == "largest_face"
    assert patches["16"]["denoise"] == 0.4
    assert patches["17"]["noise_seed"] == 42
    assert patches["23"]["frame_rate"] == 25.0
    assert patches["23"]["filename_prefix"] == "om_enhance/face_refine"


def test_upscale_binds_source_and_dials(tmp_path):
    source = tmp_path / "take.mp4"
    source.write_bytes(b"video")
    project = tmp_path / "project"
    (project / "assets/video/enhanced").mkdir(parents=True)
    inputs = {
        "operation": "video_upscale",
        "input_path": str(source),
        "output_path": str(project / "assets/video/enhanced/s1-take1-upscale.mp4"),
        "project_dir": str(project),
        "resolution": 1080,
    }
    patches = ComfyUIEnhance._workflow_patches(
        "video_upscale", inputs,
        source_fps=24.0,
        source_name="uploaded.mp4",
        ref_names=[],
        output_prefix="om_enhance/seedvr2",
    )
    assert patches["21"]["file"] == "uploaded.mp4"
    assert patches["10"]["resolution"] == 1080
    assert patches["23"]["filename_prefix"] == "om_enhance/seedvr2"


def test_models_can_be_overridden(tmp_path):
    inputs = _face_inputs(tmp_path)
    inputs["models"] = {"unet": "custom_unet.safetensors"}
    models = ComfyUIEnhance._merged_models(inputs)
    assert models["unet"] == "custom_unet.safetensors"
    assert models["clip"] == "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/tools/test_comfyui_enhance_bindings.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the class skeleton**

- 类属性按设计文档 §5.1 设置：`name="comfyui_enhance"`、`version="0.1.0"`、`tier=ToolTier.ENHANCE`、`capability="enhancement"`、`provider="comfyui"`、`stability=ToolStability.BETA`、`execution_mode=SYNC`、`determinism=SEEDED`、`runtime=LOCAL_GPU`、`dependencies=[]`、`agent_skills=["video-enhancement"]`、`fallback=None`。
- `capabilities = ["face_refinement", "video_upscaling", "detail_enhancement"]`。
- `input_schema` 必须逐项声明设计文档 §5.1 的输入：`operation`、`input_path`、`output_path`、`project_dir`、`reference_image_paths`、`prompt`、`denoise`、`face_select`、`identity_threshold`、`face_denoise_multiplier`、`resolution`、`max_resolution`、`batch_size`、`temporal_overlap`、`color_correction`、`seed`、`models`、`server_url`、`timeout_seconds`；`required` 为 `["operation", "input_path", "output_path"]`。
- `__init__(self, client=None)` 保存 `self._client = client or ComfyUIClient(capability="enhance")`。
- `_validate_inputs` 按测试的 4 条规则返回错误字符串或 `None`；`project_dir` 存在时要求 `output_path` 解析后在其内部。
- `_merged_models` 用 `DEFAULTS` 合并 `inputs.get("models")`。
- `_workflow_patches` 按设计文档 §5.1 的节点绑定表返回 patches（face_refine 与 video_upscale 两套）。`face_refine` 使用 `source_name`（绝对路径）绑节点 1；`video_upscale` 使用上传后的服务端文件名绑节点 21。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tools/test_comfyui_enhance_bindings.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/enhancement/comfyui_enhance.py tests/tools/test_comfyui_enhance_bindings.py
git commit -m "feat(enhancement): 增加 comfyui_enhance 工具契约与节点绑定"
```

---

### Task 6: `comfyui_enhance` Execution and Media Validation

**Files:**
- Modify: `tools/_comfyui/client.py`
- Modify: `tools/enhancement/comfyui_enhance.py`
- Test: `tests/tools/test_comfyui_client_upload.py`
- Test: `tests/tools/test_comfyui_enhance_execute.py`

**Interfaces:**
- Produces: `ComfyUIClient.upload_input_file(local_path, name, mime_type="application/octet-stream") -> str`；`ComfyUIEnhance.execute(inputs) -> ToolResult`；`ComfyUIEnhance._probe_media(path) -> dict`；`ComfyUIEnhance._compute_ssim(source, output) -> float | None`。
- Consumes: Task 5 的 `_validate_inputs`、`_merged_models`、`_workflow_patches`。

- [ ] **Step 1: Write the failing client test**

```python
from pathlib import Path
from unittest.mock import Mock

from tools._comfyui.client import ComfyUIClient


def test_upload_input_file_posts_to_input_folder(monkeypatch, tmp_path):
    video = tmp_path / "take.mp4"
    video.write_bytes(b"video")
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"name": "om_take.mp4", "subfolder": "", "type": "input"}
    post = Mock(return_value=response)
    monkeypatch.setattr("tools._comfyui.client.requests.post", post)
    client = ComfyUIClient(server_url="http://127.0.0.1:8188")
    name = client.upload_input_file(video, "om_take.mp4")
    assert name == "om_take.mp4"
    assert post.call_args.args[0].endswith("/upload/image")
    assert post.call_args.kwargs["files"]["image"][0] == "om_take.mp4"


def test_upload_input_file_rejects_non_input_storage(monkeypatch, tmp_path):
    video = tmp_path / "take.mp4"
    video.write_bytes(b"video")
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"name": "om_take.mp4", "subfolder": "", "type": "temp"}
    monkeypatch.setattr("tools._comfyui.client.requests.post", Mock(return_value=response))
    import pytest
    with pytest.raises(Exception):
        ComfyUIClient(server_url="http://127.0.0.1:8188").upload_input_file(video, "om_take.mp4")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/tools/test_comfyui_client_upload.py -v`
Expected: FAIL — `upload_input_file` does not exist.

- [ ] **Step 3: Refactor upload and run the client tests**

- 把 `upload_image` 的请求体逻辑抽成私有 `_upload_input(local_path, name, mime_type)`；`upload_image` 调用它并传 `"image/png"`，`upload_input_file` 传 `"application/octet-stream"`。
- 两个公开方法保持相同的响应与路径校验。

Run: `.venv/Scripts/python.exe -m pytest tests/tools/test_comfyui_client_upload.py -v`
Expected: 2 passed.

- [ ] **Step 4: Write the failing execute test**

```python
import json
from pathlib import Path

from tools.base_tool import ToolResult
from tools.enhancement.comfyui_enhance import ComfyUIEnhance


class FakeClient:
    def __init__(self, when_generate=None):
        self.uploaded = []
        self.when_generate = when_generate

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    def upload_image(self, path, name):
        self.uploaded.append(("image", Path(path).name))
        return f"server-{Path(path).name}"

    def upload_input_file(self, path, name):
        self.uploaded.append(("video", Path(path).name))
        return f"server-{Path(path).name}"

    def generate(self, workflow, output_node, dest, *, timeout=600, interval=5, resume_prompt_id=None, on_progress=None):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"out")
        if self.when_generate:
            self.when_generate(workflow)
        return [Path(dest)]


def _inputs(tmp_path, operation="video_upscale"):
    source = tmp_path / "take.mp4"
    source.write_bytes(b"video")
    project = tmp_path / "project"
    (project / "assets/video/enhanced").mkdir(parents=True)
    return {
        "operation": operation,
        "input_path": str(source),
        "output_path": str(project / "assets/video/enhanced/out.mp4"),
        "project_dir": str(project),
    }


def _media_ok(path):
    return {"duration_seconds": 7.0, "video_fps": 24.0, "video_width": 640, "video_height": 352, "audio_streams": 1}


def test_upscale_uploads_source_and_reports_provenance(tmp_path, monkeypatch):
    captured = {}
    tool = ComfyUIEnhance(client=FakeClient(when_generate=lambda wf: captured.update(wf)))
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.91)
    result = tool.execute(_inputs(tmp_path))
    assert result.success, result.error
    assert captured["21"]["inputs"]["file"] == "server-take.mp4"
    assert result.data["provenance"]["workflow"] == "enhance_seedvr2_3b_api.json"
    assert result.data["validation"]["ssim"] == 0.91


def test_face_refine_uploads_two_refs(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path, "face_refine")
    refs = []
    for name in ("face.png", "wardrobe.png"):
        path = tmp_path / name
        path.write_bytes(b"img")
        refs.append(str(path))
    inputs |= {"reference_image_paths": refs, "prompt": "subject_definitions: ..."}
    client = FakeClient()
    tool = ComfyUIEnhance(client=client)
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.95)
    result = tool.execute(inputs)
    assert result.success, result.error
    assert [kind for kind, _ in client.uploaded] == ["image", "image"]


def test_audio_loss_fails_validation(tmp_path, monkeypatch):
    tool = ComfyUIEnhance(client=FakeClient())
    sources = {"src": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 1},
               "out": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 0}}
    paths = iter(["src", "out"])
    monkeypatch.setattr(tool, "_probe_media", lambda _: sources[next(paths)])
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9)
    result = tool.execute(_inputs(tmp_path))
    assert not result.success
    assert "audio" in result.error.lower()


def test_frame_rate_change_fails_validation(tmp_path, monkeypatch):
    tool = ComfyUIEnhance(client=FakeClient())
    sources = {"src": {"duration_seconds": 7.0, "video_fps": 30.0, "audio_streams": 1},
               "out": {"duration_seconds": 7.0, "video_fps": 24.0, "audio_streams": 1}}
    paths = iter(["src", "out"])
    monkeypatch.setattr(tool, "_probe_media", lambda _: sources[next(paths)])
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9)
    result = tool.execute(_inputs(tmp_path))
    assert not result.success
    assert "frame rate" in result.error.lower()


def test_virtually_unchanged_output_returns_warning(tmp_path, monkeypatch):
    tool = ComfyUIEnhance(client=FakeClient())
    monkeypatch.setattr(tool, "_probe_media", _media_ok)
    monkeypatch.setattr(tool, "_compute_ssim", lambda *_: 0.9995)
    result = tool.execute(_inputs(tmp_path))
    assert result.success
    assert "output_virtually_unchanged" in result.data["validation"]["warnings"]


def test_unavailable_server_fails_without_fallback(tmp_path):
    class Down(FakeClient):
        def is_available(self):
            return False
        def unavailable_reason(self):
            return "ComfyUI server not reachable"
    result = ComfyUIEnhance(client=Down()).execute(_inputs(tmp_path))
    assert not result.success
    assert "not reachable" in result.error
```

- [ ] **Step 5: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/tools/test_comfyui_enhance_execute.py -v`
Expected: FAIL — `execute` does not exist.

- [ ] **Step 6: Implement `execute`**

按设计文档 §5.1 的行为实现：校验 → 服务可用 → 探测源 → 上传（face_refine 参考图；video_upscale 源视频）→ 载入内置工作流 → `patch_workflow` → `Path(output_path).parent.mkdir(parents=True, exist_ok=True)` → `client.generate(..., output_node="23", dest=Path(output_path).with_suffix(".partial.mp4"), timeout=inputs.get("timeout_seconds", 7200))` → 探测输出 → 比较音频流数量、帧率（容差 0.01）、时长（`1 / fps` 容差）→ SSIM → 校验通过后 `os.replace(partial, output_path)` → 组装 `ToolResult`。

`_probe_media` 用 `ffprobe -show_streams -show_format` 的 JSON 输出，返回 `duration_seconds`、`video_fps`、`audio_streams`（int）；ffprobe 不可用时返回空 dict，并让校验跳过而不是误判。

`_compute_ssim` 运行 `ffmpeg -i src -i out -lavfi ssim -f null -` 并从 stderr 解析 `All\:([0-9.]+)`；失败返回 `None`。

错误路径统一 `ToolResult(success=False, error=...)`；不删除已下载文件，不覆盖既有输出（若输出已存在，先写到 `output_path + ".partial"`，校验通过后再 `os.replace`）。

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/tools/test_comfyui_enhance_execute.py tests/tools/test_comfyui_enhance_bindings.py tests/tools/test_comfyui_client_upload.py -v`
Expected: 全部 passed。

- [ ] **Step 8: Commit**

```bash
git add tools/_comfyui/client.py tools/enhancement/comfyui_enhance.py tests/tools/test_comfyui_client_upload.py tests/tools/test_comfyui_enhance_execute.py
git commit -m "feat(enhancement): 打通增强工具执行与媒体校验"
```

---

### Task 7: Enhancement Selection Menu and Decision Log

**Files:**
- Create: `lib/enhancement_selection.py`
- Test: `tests/lib/test_enhancement_selection.py`

**Interfaces:**
- Produces: `ENHANCEMENT_CATEGORY = "enhancement_selection"`、`ENHANCEMENT_SUBJECT = "Post-enhancement route"`、`ROUTES`、`build_menu(registry, readiness, *, duration_seconds=0.0) -> list[dict]`、`record_selection(path, project_id, stage, route_id, options, reason) -> dict`、`require_selected_route(decision_log, route_id) -> Mapping`。

- [ ] **Step 1: Write the failing test**

```python
import json

import pytest

from lib.enhancement_selection import (
    ENHANCEMENT_SUBJECT,
    build_menu,
    record_selection,
    require_selected_route,
)


class FakeTool:
    def get_status(self):
        class S:
            value = "available"
        return S()


class FakeRegistry:
    def __init__(self, tools):
        self._tools = tools


def _readiness(face=True, upscale=True, server=True):
    return {
        "ready": face and upscale and server,
        "server_running": server,
        "routes": {
            "face_refine": {"ready": face, "blockers": [] if face else ["missing FaceRefine node"], "warnings": []},
            "video_upscale": {"ready": upscale, "blockers": [] if upscale else ["missing SeedVR2 VAE"], "warnings": []},
        },
    }


def test_menu_order_and_none_always_available():
    menu = build_menu(FakeRegistry({"comfyui_enhance": FakeTool()}), _readiness(face=False, upscale=False, server=False), duration_seconds=7.0)
    assert [row["route_id"] for row in menu] == ["none", "face_refine", "seedvr2_upscale"]
    assert menu[0]["available"] is True
    assert menu[1]["available"] is False
    assert menu[2]["available"] is False


def test_missing_tool_marks_routes_unavailable():
    menu = build_menu(FakeRegistry({}), _readiness(), duration_seconds=7.0)
    assert menu[1]["available"] is False
    assert "not registered" in menu[1]["reason"]


def test_duration_drives_estimate():
    menu = build_menu(FakeRegistry({"comfyui_enhance": FakeTool()}), _readiness(), duration_seconds=3.04)
    assert menu[2]["estimated_seconds"] == round(30 + 178 * 3.04)
    assert menu[1]["estimate_source"] == "placeholder"


def test_record_and_require_selection(tmp_path):
    path = tmp_path / "decision_log.json"
    options = [
        {"option_id": "none", "label": "No enhancement", "score": 0.5, "reason": "cheap"},
        {"option_id": "seedvr2_upscale", "label": "SeedVR2", "score": 1.0, "reason": "detail"},
    ]
    record_selection(str(path), "p", "assets", "seedvr2_upscale", options, "approved")
    log = json.loads(path.read_text(encoding="utf-8"))
    decision = log["decisions"][-1]
    assert decision["category"] == "enhancement_selection"
    assert decision["subject"] == ENHANCEMENT_SUBJECT
    assert decision["user_approved"] is True
    assert require_selected_route(log, "seedvr2_upscale")["selected"] == "seedvr2_upscale"
    with pytest.raises(ValueError):
        require_selected_route(log, "face_refine")


def test_record_rejects_route_outside_options(tmp_path):
    with pytest.raises(ValueError):
        record_selection(str(tmp_path / "d.json"), "p", "assets", "missing", [{"option_id": "none"}], "x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_enhancement_selection.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

- `ROUTES` 顺序：`none`、`face_refine`、`seedvr2_upscale`；后两者 `tool="comfyui_enhance"`，`operation` 分别为 `face_refine` / `video_upscale`。
- `build_menu`：`none` 永远可用；其余要求工具已注册且 `get_status()` 为 `available`、`readiness["server_running"]`、对应 readiness route 为 `ready`。`reason` 汇总 blocker 或缺失原因。`estimated_seconds`：`face_refine = 120 + 60*duration`、`seedvr2_upscale = 30 + 178*duration`、`none = 0`；`face_refine` 标 `estimate_source="placeholder"`，SeedVR2 标 `"measured_scale"`。
- `record_selection` 复制 `lib/video_model_selection.record_selection` 的原子写入与 `_next_decision_id` 逻辑，但使用本模块的 category/subject；校验 `route_id` 在 options 中。
- `require_selected_route` 与 `video_model_selection` 同语义：取最新同 category/subject 的 `user_approved` 决策，不匹配则抛 `ValueError`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_enhancement_selection.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/enhancement_selection.py tests/lib/test_enhancement_selection.py
git commit -m "feat(enhancement): 增加增强路线菜单与决策记录"
```

---

### Task 8: Layer 2 and Layer 3 Skills

**Files:**
- Create: `.agents/skills/video-enhancement/SKILL.md`
- Create: `skills/creative/video-enhancement.md`
- Test: `tests/contracts/test_video_enhancement_integration.py`（本任务先写技能相关断言）

**Interfaces:**
- Produces: 可被 `test_agent_skill_pointers.py` 解析的 `agent_skills=["video-enhancement"]` Layer 3 技能；Layer 2 技能供导演引用。

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_layer_three_skill_exists_and_covers_both_routes():
    path = ROOT / ".agents" / "skills" / "video-enhancement" / "SKILL.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "FaceRefine" in text and "SeedVR2" in text
    assert "frame_rate" in text and "SSIM" in text


def test_layer_two_skill_links_to_layer_three():
    path = ROOT / "skills" / "creative" / "video-enhancement.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert ".agents/skills/video-enhancement" in text
    assert "largest face" in text.lower() or "最大" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_video_enhancement_integration.py -v`
Expected: FAIL — files do not exist.

- [ ] **Step 3: Write both skills**

- `.agents/skills/video-enhancement/SKILL.md`（Layer 3）：
  - 两个工作流的节点与可绑定输入（FaceRefine 的 1/6/7/9/12/16/17/23/31/108/109；SeedVR2 的 10/13/14/21/23）。
  - 参数含义：`denoise`、`face_select`、`identity_threshold`、`face_denoise_multiplier`、`resolution`、`batch_size`、`temporal_overlap`、`color_correction`。
  - 输出契约：`23` 为输出节点；`23.frame_rate` 必须绑定源 fps；音频由源片携带。
  - 失败模式：节点缺失、模型缺失、服务未启动、SSIM 无变化、非 24 fps 源。
  - 实测数据：SeedVR2 73 帧 / 3.04 秒 / 1080 short edge ≈ 9 分钟；FaceRefine 更锐但身份轻微漂移。
- `skills/creative/video-enhancement.md`（Layer 2）：
  - 选择规则：单主脸近景 → FaceRefine；群像/远景/整体细节 → SeedVR2；两者都不选合法；不用增强补救选错的 take。
  - 门禁流程：abilities → menu → decision → apply_enhancement → 重新导出 manifest/edit/检查点。
  - 参考图规则：恰好 2 张（面部特写 + 服装/全身），来自批准角色表；无角色表不提供 FaceRefine。
  - 验收：音轨、帧率、时长、SSIM、身份对比；`compose_target` 必须同步提升。
  - 禁止事项：静默运行、改身份不告知、把增强当调色、绕过 `decision_log`。

- [ ] **Step 4: Run tests and the existing pointer contract**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_video_enhancement_integration.py tests/contracts/test_agent_skill_pointers.py -v`
Expected: 本任务断言 passed；指针测试在本工具注册后也会通过。

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/video-enhancement/SKILL.md skills/creative/video-enhancement.md tests/contracts/test_video_enhancement_integration.py
git commit -m "docs(enhancement): 增加后期增强 Layer 2/3 技能"
```

---

### Task 9: Pipeline Gate and Director Instructions

**Files:**
- Modify: `pipeline_defs/cinematic.yaml`
- Modify: `skills/pipelines/cinematic/asset-director.md`
- Modify: `skills/pipelines/cinematic/edit-director.md`
- Modify: `skills/pipelines/cinematic/compose-director.md`
- Modify: `skills/pipelines/cinematic/proposal-director.md`
- Modify: `skills/creative/video-model-selection.md`
- Test: `tests/contracts/test_video_enhancement_integration.py`（追加断言）

**Interfaces:**
- Produces: `cinematic.yaml` 的 `assets.sub_stages` 含 `enhancement_selection`，`tools_available: [comfyui_enhance]`；导演技能包含本设计的流程与限制。

- [ ] **Step 1: Append failing assertions**

```python
import yaml  # PyYAML is already a project dependency

MANIFEST = ROOT / "pipeline_defs" / "cinematic.yaml"


def test_cinematic_assets_has_enhancement_substage():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assets = next(stage for stage in manifest["stages"] if stage["name"] == "assets")
    names = [sub["name"] for sub in assets["sub_stages"]]
    assert "enhancement_selection" in names
    assert "comfyui_enhance" in assets["tools_available"]
    substage = next(sub for sub in assets["sub_stages"] if sub["name"] == "enhancement_selection")
    assert substage["human_approval_default"] is True
    assert "comfyui_enhance" in substage["tools_available"]


def test_asset_director_wires_the_gate():
    text = (ROOT / "skills" / "pipelines" / "cinematic" / "asset-director.md").read_text(encoding="utf-8")
    assert "video-enhancement.md" in text
    assert "enhancement_selection" in text
    assert "apply_enhancement" in text
    assert "require_selected_route" in text


def test_edit_director_raises_compose_target():
    text = (ROOT / "skills" / "pipelines" / "cinematic" / "edit-director.md").read_text(encoding="utf-8")
    assert "compose_target" in text
    assert "seedvr2_upscale" in text


def test_compose_director_forbids_re_enhancement():
    text = (ROOT / "skills" / "pipelines" / "cinematic" / "compose-director.md").read_text(encoding="utf-8")
    assert "comfyui_enhance" in text
    assert "silently" in text.lower() or "静默" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_video_enhancement_integration.py -v`
Expected: FAIL — manifest 与导演技能尚未更新。

- [ ] **Step 3: Update manifest and skills**

- `cinematic.yaml`：`assets.tools_available` 与 `optional_tools` 加 `comfyui_enhance`；`assets.sub_stages` 按设计文档 §5.5 增加 `enhancement_selection` 块（含 5 条 review_focus）。
- `asset-director.md`：在 Selection 步骤后加 `10. Post-enhancement gate`，写清菜单、决策、`require_selected_route`、参考图来源（2 张、批准角色表、逐镜头主角）、抽帧资格预检、`apply_enhancement`、重新导出与重新审批。
- `edit-director.md`：写清 cut 从更新后的 take 路径生成；`seedvr2_upscale` 时提升 `compose_target`；Cleanup 不重复增强。
- `compose-director.md`：写清增强是上游、不得静默再增强/替换；渲染前核对 `compose_target` 并写入 `render_report`。
- `proposal-director.md`：加一句增强在 assets 由用户选择、本地零成本只耗时间、不在 proposal 锁定。
- `video-model-selection.md`：在生成后段落交叉引用 `skills/creative/video-enhancement.md`。

- [ ] **Step 4: Run all contract tests**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_video_enhancement_integration.py tests/contracts/test_pipeline_catalog.py -v`
Expected: 全部 passed（`test_pipeline_catalog.py` 会用 pipeline manifest schema 校验修改后的 `cinematic.yaml`）。

- [ ] **Step 5: Commit**

```bash
git add pipeline_defs/cinematic.yaml skills/pipelines/cinematic/asset-director.md skills/pipelines/cinematic/edit-director.md skills/pipelines/cinematic/compose-director.md skills/pipelines/cinematic/proposal-director.md skills/creative/video-model-selection.md tests/contracts/test_video_enhancement_integration.py
git commit -m "feat(cinematic): 增加后期增强门禁与阶段指令"
```

---

### Task 10: Operational Pilot Verification

**Files:**
- Create: `docs/superpowers/plans/artifacts/2026-11-21-enhancement-pilot.md`

**Interfaces:**
- Consumes: 全部实现（工具、就绪检查、菜单、`apply_enhancement`、流水线门禁）。

- [ ] **Step 1: Run the full test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/lib tests/tools tests/contracts -q`
Expected: 全部 passed；若出现与本次改动无关的既有失败，记录并单独处理，不混入本次提交。

- [ ] **Step 2: Check readiness with ComfyUI running**

Run（先确认 `http://127.0.0.1:8188` 可访问，必要时 `comfy launch --background`）：

```bash
.venv/Scripts/python.exe - <<'PY'
import json
from lib.local_enhancement_readiness import check_enhancement_readiness

result = check_enhancement_readiness(
    r"G:/ComfyUI/Installs/ComfyUI/ComfyUI",
    [r"G:/ComfyUI/Shared/models", r"G:/ComfyUI/Installs/ComfyUI/ComfyUI/models"],
    server_running=True,
)
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
```

Expected: `ready: true`，两条 route 均 ready；记录任何 warning。

- [ ] **Step 3: Run SeedVR2 on one pilot take**

Run（输出写入试点项目；时间预算约 20 分钟，7 秒 take）：

```bash
.venv/Scripts/python.exe - <<'PY'
import json
from tools.enhancement.comfyui_enhance import ComfyUIEnhance

result = ComfyUIEnhance().execute({
    "operation": "video_upscale",
    "input_path": "projects/hyperflow-pilot/assets/video/s1-take1.mp4",
    "output_path": "projects/hyperflow-pilot/assets/video/enhanced/s1-take1-upscale.mp4",
    "project_dir": "projects/hyperflow-pilot",
    "resolution": 1080,
    "batch_size": 5,
    "temporal_overlap": 3,
    "timeout_seconds": 3600,
})
print(result.success, result.error)
print(json.dumps(result.data, ensure_ascii=False, indent=2, default=str))
PY
```

Expected: `success: True`；输出短边 1080、音轨保留、帧率 24、时长误差 ≤ 1 帧、SSIM 有实际变化。

- [ ] **Step 4: Run FaceRefine on the smoke clip**

Run（使用实验资产的两张参考图）：

```bash
.venv/Scripts/python.exe - <<'PY'
import json
from tools.enhancement.comfyui_enhance import ComfyUIEnhance

source_prompt = json.loads(
    open("projects/_h3-api-export/smoke_singularity_ref2v.api.json", encoding="utf-8").read()
)["2"]["inputs"]["value"]

result = ComfyUIEnhance().execute({
    "operation": "face_refine",
    "input_path": "G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_face_source_07mp.mp4",
    "output_path": "projects/hyperflow-pilot/assets/video/enhanced/smoke-face-refine.mp4",
    "project_dir": "projects/hyperflow-pilot",
    "reference_image_paths": [
        "G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_ref_cui_zhu.png",
        "G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_ref_cui_zhu_wardrobe.png",
    ],
    "prompt": source_prompt,
    "denoise": 0.4,
    "timeout_seconds": 3600,
})
print(result.success, result.error)
print(json.dumps(result.data, ensure_ascii=False, indent=2, default=str))
PY
```

Expected: `success: True`；输出可播放、音画同步、帧率/时长不变；人工对比身份。

- [ ] **Step 5: Apply enhancement to the pilot selection and re-compose**

```python
import json
from pathlib import Path

from lib.checkpoint import write_checkpoint
from lib.enhancement_selection import record_selection
from lib.narrative_assets import NarrativeAssets

project = Path("projects/hyperflow-pilot")
enhanced_rel = "assets/video/enhanced/s1-take1-upscale.mp4"
enhanced_abs = (project / enhanced_rel).resolve()

catalog = NarrativeAssets(project)
catalog.apply_enhancement(
    "s1", "take1", enhanced_rel,
    duration_seconds=7.292,  # ffprobe of the enhanced file; edit still trims to 7.0
    enhancement={
        "operation": "video_upscale",
        "model": "SeedVR2 3B FP8",
        "source_path": "assets/video/s1-take1.mp4",
        "parameters": {"resolution": 1080},
        "workflow_hash_sha256": "<workflow hash printed by Step 3>",
    },
)
manifest = catalog.asset_manifest()

# Keep the approved 7.0 / 6.0 / 7.0 edit; only repoint s1 at the enhanced file.
edit = json.loads((project / "artifacts/edit_decisions.json").read_text(encoding="utf-8"))
for cut in edit["cuts"]:
    if cut["id"] == "s1":
        cut["source"] = str(enhanced_abs)
        cut["reason"] = "enhanced with SeedVR2 3B FP8; original take assets/video/s1-take1.mp4"
edit["metadata"]["compose_target"] = {"width": <probed_w>, "height": <probed_h>, "fit": "pad"}

write_checkpoint(project.parent, project.name, "assets", "completed",
                 {"asset_manifest": manifest}, human_approval_required=True, human_approved=True)
write_checkpoint(project.parent, project.name, "edit", "completed",
                 {"edit_decisions": edit})

record_selection(
    str(project / "decision_log.json"), "hyperflow-pilot", "assets",
    "seedvr2_upscale",
    [
        {"option_id": "none", "label": "No post-enhancement", "score": 0.5, "reason": "no resolution gain"},
        {"option_id": "face_refine", "label": "H3-FaceRefine", "score": 0.6, "reason": "multi-character shot; largest face only", "rejected_because": "s1 has two children"},
        {"option_id": "seedvr2_upscale", "label": "SeedVR2 3B FP8", "score": 1.0, "reason": "whole-shot detail and resolution"},
    ],
    "approved: s1 only; s2/s3 keep original takes",
)
```

`<probed_w>` / `<probed_h>` 取 Task 10 Step 3 返回的 `result.data["enhanced"]` 宽高。然后：

```bash
.venv/Scripts/python.exe - <<'PY'
from tools.video.video_compose import VideoCompose
result = VideoCompose().execute({
    "operation": "render",
    "project_dir": "projects/hyperflow-pilot",
    "render_runtime": "ffmpeg",
    "output_path": "projects/hyperflow-pilot/renders/final-enhanced.mp4",
})
print(result.success, result.error)
PY
```

- 用 ffprobe 确认分辨率提升、24 fps、约 20 秒、一条音轨；确认没有被叙事选片守卫拒绝。

- [ ] **Step 6: Write the pilot report and commit**

在 `docs/superpowers/plans/artifacts/2026-11-21-enhancement-pilot.md` 记录：环境、命令、SeedVR2/FaceRefine 实测耗时与显存、输出规格、SSIM、身份对比结论、成片规格、遗留问题（FaceRefine 最大脸限制、SeedVR2 时间成本）。

```bash
git add docs/superpowers/plans/artifacts/2026-11-21-enhancement-pilot.md
git commit -m "docs(enhancement): 记录本地增强试点结果"
```

---

## Self-Review Notes

- 规格覆盖：schema、就绪检查、工作流、工具契约/执行、叙事选片一致性、菜单/决策、两级技能、流水线门禁、运行验收均有对应任务。
- 类型一致：`apply_enhancement`、`_workflow_patches`、`upload_input_file`、`build_menu`、`require_selected_route` 在后续任务中复用的名字与参数保持一致。
- Review Focus 的 5 条都有测试：Task 6（帧率、音轨、服务不可达）、Task 5（单参考图、项目外输出）、Task 4（重选/过期路径守卫）、Task 2/7（就绪与菜单）。
