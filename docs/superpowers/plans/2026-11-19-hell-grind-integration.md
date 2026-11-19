# Hell-Grind × OpenMontage Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the v4 Hell-Grind integration: local-first MiniMax H3/HyperFlow cinematic generation, a user-approved video-model selection gate, asset-first narrative production, and the tests that pin each behavior.

**Architecture:** Three thin layers — instruction documents (Layer 3 skills, Layer 2 norms, cinematic director skills), a small Python helper layer for model catalog/selection persistence and local readiness, and the existing ComfyUI tool extended with a HyperFlow workflow family. Python stores and validates facts; the agent still makes creative and routing decisions.

**Tech Stack:** Python 3.10+, pytest, jsonschema, PyYAML, ComfyUI 0.43+, ModelScope CLI, HyperFlow H3 Flash.

**Spec:** `docs/hell-grind-integration.md`

## Global Constraints

- Run commands with the project virtualenv: `.venv/Scripts/python.exe -m pytest` on Windows, or `make test-contracts`.
- Model downloads go to **ModelScope first**; HuggingFace (`HF_ENDPOINT=https://hf-mirror.com`) is fallback only.
- Local route order is fixed: HyperFlow GGUF → HyperFlow INT8 → H3 local → cloud H3 → Seedance 2.5 → Pika H3 Flex.
- HyperFlow weights use the MiniMax H3 Community License. The download script must refuse to download without `--accept-license`.
- 16 GB VRAM: smoke tests run at 5 seconds, 768P, 6 steps. The P0.5 smoke uses INT8 first because its API workflows are bundled; GGUF remains the memory fallback.
- Every `agent_skills` pointer must resolve to `.agents/skills/<name>/SKILL.md` or `.agents/skills/<name>.md`.
- `decision_log` entries validate against `schemas/artifacts/decision_log.schema.json`; no extra keys.
- No orchestration logic in Python. Helpers may build catalogs, validate, and persist; they may not choose creative options.
- One commit per task. Commit messages use the project's `type(scope): 中文摘要` style.

## Review Focus

- A generation starts with no matching `provider_selection` / `Video model and route` decision → `require_selected_route` must raise, not return a default.
- The menu silently drops a route (HyperFlow, H3 Max, Pika, Seedance) → catalog test fails.
- A local checkpoint is missing → readiness reports a blocker with a path, not an exception.
- HyperFlow API workflow node IDs drift → binding test fails on class type or input name.
- A decision log entry carries a timestamp or other extra key → schema validation fails.

---

### Task 1: Import the Hell-Grind Layer 3 skills

**Files:**
- Create: `.agents/skills/cinedance/SKILL.md`
- Create: `.agents/skills/acting-system/SKILL.md`
- Create: `.agents/skills/lira-image-prompts/SKILL.md`
- Create: `.agents/skills/hyperflow-h3/SKILL.md`
- Test: `tests/contracts/test_hell_grind_skills.py`

**Interfaces:**
- Consumes: source files under `D:\AI\higgsfield-hell-grind-opensource\skills\`.
- Produces: three skill directories with `name:` frontmatter used by Task 3 pointers.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = {
    "cinedance": "ONE-TAKE",
    "acting-system": "acting is BEHAVIOR",
    "lira-image-prompts": "Soul Cinema",
}


@pytest.mark.parametrize("slug,phrase", SKILLS.items())
def test_skill_exists_with_frontmatter(slug, phrase):
    path = ROOT / ".agents" / "skills" / slug / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    frontmatter, body = text.split("---", 2)[1], text.split("---", 2)[2]
    assert f"name: {slug}" in frontmatter
    assert len(body) > 5000
    assert phrase.lower() in body.lower()


def test_hyperflow_skill_records_routes_and_license():
    text = (ROOT / ".agents" / "skills" / "hyperflow-h3" / "SKILL.md").read_text(encoding="utf-8")
    assert "HyperFlowINT8Loader" in text
    assert "MiniMax H3 Community License" in text
    assert "ModelScope" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_skills.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Copy the source skills and prepend frontmatter**

Run this once from the repo root; it stops if the source archive is missing:

```bash
.venv/Scripts/python.exe - <<'PY'
from pathlib import Path

src = Path(r"D:\AI\higgsfield-hell-grind-opensource\skills")
dst = Path.cwd() / ".agents" / "skills"
items = {
    "cinedance": ("CINEDANCE HIGGSFIELD SKILL.md",
                  "CINEDANCE V4 — Seedance 2.0/2.5 prompt director: 15-section shot specification, spatial blocking, optics, physics, and QA."),
    "acting-system": ("ACTING SKILL.md",
                      "ACTING SYSTEM — character performance for AI video: behavior under pressure, objectives, obstacles, tactics, and physical detail."),
    "lira-image-prompts": ("LIRA SKILL.md",
                           "Lira — image prompt optimization for character sheets, locations, props, and edits across Soul Cinema, Nano Banana Pro, Seedream, and GPT Image 2."),
}
for slug, (filename, description) in items.items():
    body = (src / filename).read_text(encoding="utf-8")
    target = dst / slug / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nname: {slug}\ndescription: |\n  {description}\n---\n\n{body}", encoding="utf-8")
    print(target, len(body))
PY
```

Then author `.agents/skills/hyperflow-h3/SKILL.md` yourself. It must cover:

- Frontmatter: `name: hyperflow-h3`, description naming Video Rebirth's 4/6/8-step MiniMax-H3 checkpoint.
- Two implementations: official `comfyui-hyperflow-flash` (`HyperFlowLoader`, `HyperFlowGGUFLoader`, `HyperFlowSigmas`) and community `comfyui-hyperflow-int8-nodes` (`HyperFlowINT8Loader`).
- `fl2va` (t2v / i2v / flf2v) and `ref2va` (ref2v) checkpoints; INT8 and GGUF filenames.
- Node flow and bindings: prompt node `5`, seed node `8`, steps node `6`, output node `14`; ref images via nodes `20`/`21`.
- Download source: `VideoRebirthAI/hyperflow-h3-flash` on ModelScope; VAEs from `Comfy-Org/MiniMax-H3`.
- Constraints: ComfyUI ≥ 0.43.0, `--fast-disk` for GGUF, 16 GB VRAM caveat, `MiniMax H3 Community License` territorial limits.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_skills.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/cinedance .agents/skills/acting-system .agents/skills/lira-image-prompts .agents/skills/hyperflow-h3 tests/contracts/test_hell_grind_skills.py
git commit -m "feat(skills): 导入 Hell-Grind 技能并新增 HyperFlow 说明"
```

---

### Task 2: Add the Layer 2 narrative and model-selection norms

**Files:**
- Create: `skills/creative/narrative-consistency.md`
- Create: `skills/creative/video-model-selection.md`
- Modify: `skills/creative/video-gen-prompting.md`
- Test: `tests/contracts/test_narrative_norms.py`

**Interfaces:**
- Consumes: the rules in `docs/hell-grind-integration.md` sections 3, 4, and 6.
- Produces: two Layer 2 skills referenced by `required_skills` in Task 4 and by director skills in Task 11.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {
    "narrative-consistency.md": [
        "## Asset order", "## Character sheets", "## Scene lock",
        "## Stress test", "## Take budget",
    ],
    "video-model-selection.md": [
        "## Local first", "## Selection gate", "## Menu",
        "## Draft and final", "## No silent fallback",
    ],
}


def test_norms_have_required_sections():
    for name, headings in REQUIRED.items():
        text = (ROOT / "skills" / "creative" / name).read_text(encoding="utf-8")
        for heading in headings:
            assert heading in text, f"{name} missing {heading}"


def test_video_prompting_links_to_norms():
    text = (ROOT / "skills" / "creative" / "video-gen-prompting.md").read_text(encoding="utf-8")
    assert "narrative-consistency" in text
    assert "cinedance" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_narrative_norms.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the two norms and the cross-link**

`skills/creative/narrative-consistency.md` must contain, under the five headings:

- Asset order: descriptor text + reference image; character sheet = face close-up, front full-body **without head**, back full-body; location plate; prop sheet; stress test before locking.
- Character sheets: separate texture references for hair, skin, background, and fabric; keep the descriptor word-for-word in every shot prompt.
- Scene lock: empty plate, anchor objects, one light source and one shadow direction, first second is a wordless wide shot, optional 360° empty-scene sweep for reverse angles.
- Stress test: identity, wardrobe, spatial readability, and reusability; failure returns to asset design, never to shot generation.
- Take budget: 2–4 takes per shot; local drafts at lower resolution; a family or route change needs a logged decision.

`skills/creative/video-model-selection.md` must contain, under the five headings:

- Local first: `HyperFlow GGUF → HyperFlow INT8 → H3 local → cloud H3 → Seedance 2.5 → Pika H3 Flex`.
- Selection gate: proposal chooses family and preferred route; assets confirms model id, resolution, duration, take count, and total cost before the first generation.
- Menu: read status and `estimate_cost` from the registry; show local routes first; show missing local files as blockers with a download hint.
- Draft and final: lower resolution within the same family is allowed; local→cloud or cross-family is a logged, approved change.
- No silent fallback: an unavailable selected route stops the run; re-selection is required.

In `skills/creative/video-gen-prompting.md`, add a Seedance 2.5 row/paragraph that points to `creative/narrative-consistency.md` and `.agents/skills/cinedance/SKILL.md`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_narrative_norms.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/creative/narrative-consistency.md skills/creative/video-model-selection.md skills/creative/video-gen-prompting.md tests/contracts/test_narrative_norms.py
git commit -m "docs(skills): 增加叙事一致性与视频模型选择规范"
```

---

### Task 3: Wire the new skills into tool pointers

**Files:**
- Modify: `tools/video/seedance_video.py`
- Modify: `tools/video/seedance_replicate.py`
- Modify: `tools/video/seedance_ark.py`
- Modify: `tools/video/higgsfield_video.py`
- Modify: `tools/video/video_selector.py`
- Modify: `tools/video/comfyui_video.py`
- Modify: `tools/graphics/seedream_image.py`
- Modify: `tools/graphics/openai_image.py`
- Modify: `tools/graphics/gemini_fal_image.py`
- Test: `tests/contracts/test_hell_grind_skill_wiring.py`

**Interfaces:**
- Consumes: skill slugs from Tasks 1–2.
- Produces: `agent_skills` lists later tasks and the existing pointer test rely on.

- [ ] **Step 1: Write the failing test**

```python
from tools.graphics.gemini_fal_image import GeminiFalImage
from tools.graphics.openai_image import OpenAIImage
from tools.graphics.seedream_image import SeedreamImage
from tools.video.comfyui_video import ComfyUIVideo
from tools.video.higgsfield_video import HiggsFieldVideo
from tools.video.seedance_ark import SeedanceArkVideo
from tools.video.seedance_replicate import SeedanceReplicate
from tools.video.seedance_video import SeedanceVideo
from tools.video.video_selector import VideoSelector


def test_seedance_family_reads_cinedance_and_acting():
    for cls in (SeedanceVideo, SeedanceReplicate, SeedanceArkVideo, HiggsFieldVideo):
        assert {"cinedance", "acting-system"} <= set(cls().agent_skills)


def test_selector_reads_local_and_narrative_skills():
    assert {"cinedance", "acting-system", "hyperflow-h3"} <= set(VideoSelector().agent_skills)


def test_comfyui_video_advertises_hyperflow():
    assert "hyperflow-h3" in ComfyUIVideo().agent_skills


def test_image_tools_read_lira():
    for cls in (SeedreamImage, OpenAIImage, GeminiFalImage):
        assert "lira-image-prompts" in cls().agent_skills
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_skill_wiring.py -v`
Expected: FAIL on the first missing skill.

- [ ] **Step 3: Add the pointers**

For each class, extend the existing list rather than replacing it:

- `SeedanceVideo`, `SeedanceReplicate`, `SeedanceArkVideo`, `HiggsFieldVideo`: append `"cinedance", "acting-system"`.
- `VideoSelector`: append `"cinedance", "acting-system", "hyperflow-h3"`.
- `ComfyUIVideo`: append `"hyperflow-h3"`.
- `SeedreamImage`, `OpenAIImage`: append `"lira-image-prompts"`.
- `GeminiFalImage`: add `agent_skills = ["lira-image-prompts"]`.

- [ ] **Step 4: Run both pointer tests**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_skill_wiring.py tests/contracts/test_agent_skill_pointers.py -v`
Expected: all pass; every pointer resolves.

- [ ] **Step 5: Commit**

```bash
git add tools/video/seedance_video.py tools/video/seedance_replicate.py tools/video/seedance_ark.py tools/video/higgsfield_video.py tools/video/video_selector.py tools/video/comfyui_video.py tools/graphics/seedream_image.py tools/graphics/openai_image.py tools/graphics/gemini_fal_image.py tests/contracts/test_hell_grind_skill_wiring.py
git commit -m "feat(tools): 为生成工具挂接 Hell-Grind 与 HyperFlow 技能"
```

---

### Task 4: Update the cinematic manifest

**Files:**
- Modify: `pipeline_defs/cinematic.yaml`
- Test: `tests/contracts/test_hell_grind_integration.py`

**Interfaces:**
- Consumes: skill names from Tasks 1–2.
- Produces: `production_modes.narrative_generated.agent_skills`, `assets.sub_stages`, and `required_skills` used by the director skills and runtime checks.

- [ ] **Step 1: Write the failing test**

```python
from lib.pipeline_loader import load_pipeline


def test_narrative_mode_lists_local_skills_first():
    manifest = load_pipeline("cinematic")
    modes = {mode["name"]: mode for mode in manifest["production_modes"]}
    skills = modes["narrative_generated"]["agent_skills"]
    assert skills[:2] == ["hyperflow-h3", "minimax-h3"]
    assert {"cinedance", "acting-system", "lira-image-prompts"} <= set(skills)


def test_assets_has_asset_and_model_gates():
    manifest = load_pipeline("cinematic")
    assets = next(stage for stage in manifest["stages"] if stage["name"] == "assets")
    sub = {stage["name"]: stage for stage in assets["sub_stages"]}
    assert sub["asset_sheets"]["human_approval_default"] is True
    assert sub["model_selection"]["human_approval_default"] is True


def test_required_skills_include_the_two_norms():
    manifest = load_pipeline("cinematic")
    assert {"creative/narrative-consistency", "creative/video-model-selection"} <= set(manifest["required_skills"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_integration.py -v`
Expected: FAIL on the first assertion.

- [ ] **Step 3: Edit `pipeline_defs/cinematic.yaml`**

- Append to `required_skills`: `creative/narrative-consistency`, `creative/video-model-selection`.
- Replace the `narrative_generated.agent_skills` line with:
  ```yaml
  agent_skills: [hyperflow-h3, minimax-h3, cinedance, acting-system, lira-image-prompts, comfyui]
  ```
- Under the `assets` stage, add:
  ```yaml
  sub_stages:
    - name: asset_sheets
      description: "Character, location, and prop sheets approved before batch take generation"
      human_approval_default: true
    - name: model_selection
      description: "User selects the video model family and route before the first generation"
      human_approval_default: true
      tools_available: [video_selector]
  ```
- Add to `assets.review_focus`: `Asset sheets are approved before any batch take generation` and `The user selected the model family and route before the first generation`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_integration.py tests/contracts/test_narrative_cinematic.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline_defs/cinematic.yaml tests/contracts/test_hell_grind_integration.py
git commit -m "feat(cinematic): 增加资产与模型选择门禁"
```

---

### Task 5: Add the video-model selection catalog and decision persistence

**Files:**
- Create: `lib/video_model_selection.py`
- Test: `tests/lib/test_video_model_selection.py`

**Interfaces:**
- Produces:
  - `VideoRoute` dataclass with fields `route_id, family, route, tool, model, priority, local, operations, notes, model_family`.
  - `default_routes() -> list[VideoRoute]`
  - `build_menu(registry, *, duration: int = 5) -> list[dict]`
  - `render_menu(routes: Sequence[Mapping]) -> str`
  - `require_selected_route(decision_log: Mapping, route_id: str) -> Mapping`
  - `record_selection(path, project_id, stage, route, options, reason) -> dict`
- Consumes: `tools.tool_registry.registry`, `schemas/artifacts/decision_log.schema.json`.

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

import jsonschema
import pytest

from lib.video_model_selection import (
    build_menu, default_routes, record_selection, render_menu, require_selected_route,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeTool:
    def __init__(self, status="available", cost=0.5):
        self._status, self._cost = status, cost

    def get_status(self):
        return type("S", (), {"value": self._status})()

    def estimate_cost(self, inputs):
        return self._cost

    def get_info(self):
        return {"install_instructions": "start the ComfyUI server"}


class FakeRegistry:
    def __init__(self):
        self._tools = {
            "comfyui_video": FakeTool("unavailable", 0.0),
            "minimax_video": FakeTool("available", 0.65),
        }


def test_routes_cover_local_and_cloud_paths():
    ids = {route.route_id for route in default_routes()}
    assert {"hyperflow_gguf", "hyperflow_int8", "h3_local", "minimax_direct",
            "atlas_h3", "comfyui_h3_api", "h3_max", "pika_h3_flex",
            "seedance_fal", "atlas_seedance"} <= ids


def test_menu_orders_local_first_and_reads_status():
    menu = build_menu(FakeRegistry())
    assert [item["route_id"] for item in menu[:3]] == ["hyperflow_gguf", "hyperflow_int8", "h3_local"]
    assert menu[0]["available"] is False
    assert "ComfyUI" in menu[0]["setup"]
    direct = next(item for item in menu if item["route_id"] == "minimax_direct")
    assert direct["available"] is True and direct["cost_5s"] == 0.65
    assert "hyperflow_gguf" in render_menu(menu)


def test_require_selected_route_raises_without_approval():
    with pytest.raises(ValueError, match="No user-approved"):
        require_selected_route({"decisions": []}, "hyperflow_gguf")


def test_record_selection_appends_and_validates(tmp_path):
    path = tmp_path / "decision_log.json"
    local_options = [{"option_id": "hyperflow_gguf", "label": "HyperFlow GGUF", "score": 1.0, "reason": "local first"}]
    cloud_options = [
        {"option_id": "hyperflow_gguf", "label": "HyperFlow GGUF", "score": 0.6, "reason": "local OOM"},
        {"option_id": "atlas_h3", "label": "Atlas H3", "score": 1.0, "reason": "local OOM fallback"},
    ]
    record_selection(path, "film", "assets", {"route_id": "hyperflow_gguf"}, local_options, "local first")
    record_selection(path, "film", "assets", {"route_id": "atlas_h3"}, cloud_options, "local OOM")
    log = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/artifacts/decision_log.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(log, schema)
    assert len(log["decisions"]) == 2
    assert require_selected_route(log, "atlas_h3")["selected"] == "atlas_h3"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_video_model_selection.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `lib/video_model_selection.py`**

Route table (priority is fixed; local first):

| route_id | family | tool | model | priority | local |
|---|---|---|---|---|---|
| hyperflow_gguf | MiniMax H3 HyperFlow | comfyui_video | minimax_h3_hyperflow_local | 1 | yes |
| hyperflow_int8 | MiniMax H3 HyperFlow | comfyui_video | minimax_h3_hyperflow_local | 2 | yes |
| h3_local | MiniMax H3 | comfyui_video | minimax_h3_local | 3 | yes |
| minimax_direct | MiniMax H3 | minimax_video | MiniMax-H3 | 4 | no |
| minimax_fal | MiniMax H3 | minimax_fal_video | hailuo-03 | 5 | no |
| runway_h3 | MiniMax H3 | runway_video | hailuo3 | 6 | no |
| atlas_h3 | MiniMax H3 | atlas_video | minimax/h3/text-to-video | 7 | no |
| comfyui_h3_api | MiniMax H3 | comfyui_video | minimax_h3_api | 8 | no |
| h3_max | MiniMax H3 Max | h3_max_video | h3-max | 9 | no |
| pika_h3_flex | Pika H3 Flex | pika_video | pika-h3-flex | 10 | no |
| seedance_fal | Seedance 2.5 | seedance_video | 2.5 | 11 | no |
| seedance_ark | Seedance 2.5 | seedance_ark | 2.5 | 12 | no |
| atlas_seedance | Seedance 2.5 | atlas_video | bytedance/seedance-2.5/text-to-video | 13 | no |

Implementation rules:

- `build_menu` reads `getattr(registry, "_tools", {})`; missing tool → `available=False`, `status="unavailable"`.
- Status is `getattr(tool.get_status(), "value", str(tool.get_status())).lower()`; available only when it equals `"available"`.
- Cost is `0.0` for local routes, otherwise `round(float(tool.estimate_cost({"prompt": "x", "duration": duration})), 2)`; an exception yields `None`.
- Each item is a dict with `route_id, family, route, tool, model, priority, local, operations, notes, available, status, cost_5s, setup`. `setup` is `tool.get_info().get("install_instructions")` when the tool is unavailable, else `None`; a missing or failing `get_info` yields `None`.
- `render_menu` sorts by `(priority, route_id)` and prints one line per route: `priority. route_id family tool cost status — notes`.
- `require_selected_route` filters `category == "provider_selection"` and `subject == "Video model and route"`, uses the **last** match, raises `ValueError("No user-approved video model selection")` when empty, raises when `user_approved` is not `True`, and raises when `selected != route_id`.
- `record_selection` creates or loads `{"version": "1.0", "project_id": ..., "decisions": []}`, derives the next `decision_id` from the largest existing `d-N` (default `d-001`), requires `route["route_id"]` to appear in `options_considered`, appends `{decision_id, stage, category: "provider_selection", subject: "Video model and route", options_considered: [...], selected: route["route_id"], reason, user_visible: True, user_approved: True}`, validates with jsonschema, and writes atomically (temp file + `os.replace`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_video_model_selection.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/video_model_selection.py tests/lib/test_video_model_selection.py
git commit -m "feat(selection): 增加视频模型目录与用户选择持久化"
```

---

### Task 6: Add the local HyperFlow readiness checker

**Files:**
- Create: `lib/local_video_readiness.py`
- Test: `tests/lib/test_local_video_readiness.py`

**Interfaces:**
- Produces: `check_hyperflow_readiness(comfyui_root, model_roots, *, server_running) -> dict`.
- Return shape: `{"ready": bool, "comfyui_version": str | None, "checks": {name: {"ok": bool, "path": str | None, "detail": str}}, "blockers": list[str], "warnings": list[str]}`.
- Consumes: filesystem only; no ComfyUI network calls.

- [ ] **Step 1: Write the failing test**

```python
from lib.local_video_readiness import check_hyperflow_readiness


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_reports_ready_when_all_files_exist(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    for node in ("comfyui-hyperflow-flash", "comfyui-hyperflow-int8-nodes", "ComfyUI-GGUF"):
        (root / "custom_nodes" / node).mkdir(parents=True)
    models = tmp_path / "models"
    for name in (
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "minimax_h3_video_vae_fp16.safetensors",
        "minimax_h3_audio_vae_fp32.safetensors",
        "minimax_h3_sol_vae_int8_convrot.safetensors",
        "minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf",
        "minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf",
    ):
        _write(models / name)
    result = check_hyperflow_readiness(root, [models], server_running=True)
    assert result["ready"] is True
    assert result["blockers"] == []


def test_missing_checkpoint_is_a_blocker(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=True)
    assert result["ready"] is False
    assert any("hyperflow" in item.lower() for item in result["blockers"])


def test_old_comfyui_is_a_blocker(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.42.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=True)
    assert any("0.43" in item for item in result["blockers"])


def test_missing_sol_vae_is_a_warning(tmp_path):
    root = tmp_path / "ComfyUI"
    _write(root / "comfyui_version.py", '__version__ = "0.45.0"')
    result = check_hyperflow_readiness(root, [tmp_path / "models"], server_running=False)
    assert any("sol" in item.lower() for item in result["warnings"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_local_video_readiness.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `lib/local_video_readiness.py`**

- Parse `comfyui_version.py` with `re.search(r'__version__\s*=\s*"([^"]+)"', ...)`; compare version tuples numerically.
- Check custom node directories exactly by name.
- Search each model root recursively for each required basename; record the first match.
- Required blockers: ComfyUI ≥ 0.43.0, server running, both HyperFlow checkpoints (`*hyperflow*fl2va*` and `*hyperflow*ref2va*`), text encoder, video VAE, audio VAE.
- Warning only: `minimax_h3_sol_vae_int8_convrot.safetensors`.
- Every blocker string names the missing item and the searched roots.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_local_video_readiness.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/local_video_readiness.py tests/lib/test_local_video_readiness.py
git commit -m "feat(local): 增加 HyperFlow 本地就绪检查"
```

---

### Task 7: Add the HyperFlow family to `comfyui_video`

**Files:**
- Modify: `tools/video/comfyui_video.py`
- Modify: `tools/_comfyui/metadata.py`
- Test: `tests/contracts/test_comfyui_tools.py`

**Interfaces:**
- Consumes: `BUNDLED_MODEL_STACKS` and the existing custom-workflow path.
- Produces: `model_family="minimax_h3_hyperflow_local"`, accepted by `ComfyUIVideo.execute`.

- [ ] **Step 1: Write the failing test**

Append to `tests/contracts/test_comfyui_tools.py`:

```python
def test_hyperflow_family_is_declared():
    tool = ComfyUIVideo()
    assert "minimax_h3_hyperflow_local" in tool.input_schema["properties"]["model_family"]["enum"]
    assert "hyperflow-h3" in tool.agent_skills


def test_hyperflow_family_requires_a_workflow():
    result = ComfyUIVideo().execute({
        "prompt": "a rain-soaked alley",
        "model_family": "minimax_h3_hyperflow_local",
        "output_path": "out.mp4",
    })
    assert not result.success
    assert result.data["setup_required"] is True
    names = {item["name"] for item in result.data["model_stack"]}
    assert "minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf" in names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_comfyui_tools.py -v -k hyperflow`
Expected: FAIL; the family is absent.

- [ ] **Step 3: Implement**

- Add `"minimax_h3_hyperflow_local"` to the `model_family` enum and to the description.
- In `execute`, before the generic custom-workflow check, add a branch mirroring `minimax_h3_local`: without `workflow_json`/`workflow_path`, **without `checkpoint_name`**, and without `resume_prompt_id`, return `ToolResult(success=False, data={"provider": "comfyui", "model": "MiniMax-H3 HyperFlow", "setup_required": True, "workflow_templates": {"t2v": "tools/_comfyui/workflows/hyperflow_int8_t2v_api.json", "i2v": "...hyperflow_int8_i2v_api.json", "flf2v": "...hyperflow_int8_flf2v_api.json", "ref2v": "...hyperflow_int8_ref2v_api.json"}, "model_stack": BUNDLED_MODEL_STACKS["minimax-h3-hyperflow-local"]}, error="minimax_h3_hyperflow_local requires checkpoint_name or an API-format workflow via workflow_json/workflow_path plus output_node.")`.
- `_model_name`: return `inputs.get("workflow_model") or "MiniMax-H3 HyperFlow (local ComfyUI workflow)"` for this family.
- `_workflow_provenance`: treat the family as local H3; use the HyperFlow model stack when `workflow_model_stack` is absent.
- In `tools/_comfyui/metadata.py`, add a `"minimax-h3-hyperflow-local"` stack with these entries:
  - diffusion_model `minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf`, ModelScope URL `https://modelscope.cn/models/VideoRebirthAI/hyperflow-h3-flash`
  - diffusion_model `minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf`, same URL
  - text_encoder `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`, ModelScope `Comfy-Org/MiniMax-H3`
  - video_vae `minimax_h3_video_vae_fp16.safetensors`, same
  - audio_vae `minimax_h3_audio_vae_fp32.safetensors`, same
  - vae `minimax_h3_sol_vae_int8_convrot.safetensors`, same

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_comfyui_tools.py -v -k hyperflow`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/video/comfyui_video.py tools/_comfyui/metadata.py tests/contracts/test_comfyui_tools.py
git commit -m "feat(comfyui): 增加 MiniMax-H3 HyperFlow 本地模型族"
```

---

### Task 8: Bundle the HyperFlow API workflows and provenance

**Files:**
- Create: `tools/_comfyui/workflows/hyperflow_int8_t2v_api.json`
- Create: `tools/_comfyui/workflows/hyperflow_int8_i2v_api.json`
- Create: `tools/_comfyui/workflows/hyperflow_int8_flf2v_api.json`
- Create: `tools/_comfyui/workflows/hyperflow_int8_ref2v_api.json`
- Create: `tools/_comfyui/workflows/HYPERFLOW_PROVENANCE.md`
- Test: `tests/contracts/test_hyperflow_workflows.py`

**Interfaces:**
- Consumes: upstream API workflows from `BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI`.
- Produces: workflow files consumed by Task 9's bindings and Task 13's smoke test.

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / "tools" / "_comfyui" / "workflows"
CASES = {
    "hyperflow_int8_t2v_api.json": "MiniMaxH3ImageToVideo",
    "hyperflow_int8_i2v_api.json": "MiniMaxH3ImageToVideo",
    "hyperflow_int8_flf2v_api.json": "MiniMaxH3ImageToVideo",
    "hyperflow_int8_ref2v_api.json": "MiniMaxH3ReferenceToVideo",
}


def test_workflows_are_api_format_and_complete():
    for filename, node_class in CASES.items():
        data = json.loads((WORKFLOWS / filename).read_text(encoding="utf-8"))
        classes = {node["class_type"] for node in data.values()}
        assert {"HyperFlowINT8Loader", "HyperFlowSigmas", "SaveVideo", node_class} <= classes
        assert all("class_type" in node for node in data.values())


def test_reference_workflow_has_two_image_loaders():
    data = json.loads((WORKFLOWS / "hyperflow_int8_ref2v_api.json").read_text(encoding="utf-8"))
    classes = [node["class_type"] for node in data.values()]
    assert classes.count("LoadImage") >= 2


def test_provenance_recorded():
    text = (WORKFLOWS / "HYPERFLOW_PROVENANCE.md").read_text(encoding="utf-8")
    assert "BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI" in text
    assert "MiniMax H3 Community License" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hyperflow_workflows.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Download the four workflows and write provenance**

```bash
BASE="https://huggingface.co/BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI/resolve/main/workflows/api"
for name in t2v i2v flf2v ref2v; do
  curl -sSL --max-time 60 "$BASE/hyperflow_int8_${name}_api.json" \
    -o "tools/_comfyui/workflows/hyperflow_int8_${name}_api.json"
done
```

Then write `HYPERFLOW_PROVENANCE.md` with the source repo URL, the four filenames, the upstream license line (`MiniMax H3 Community License`), and a note that OpenMontage does not relicense them.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hyperflow_workflows.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/_comfyui/workflows/hyperflow_int8_*_api.json tools/_comfyui/workflows/HYPERFLOW_PROVENANCE.md tests/contracts/test_hyperflow_workflows.py
git commit -m "feat(comfyui): 内置 HyperFlow API 工作流与来源说明"
```

---

### Task 9: Bind HyperFlow inputs and support its four operations

**Files:**
- Modify: `tools/video/comfyui_video.py`
- Test: `tests/contracts/test_narrative_workflow.py`

**Interfaces:**
- Consumes: workflow files from Task 8; `ComfyUIClient.bind_workflow`.
- Produces: `execute` accepts `operation` values `text_to_video`, `image_to_video`, `first_last_frame_to_video`, `reference_to_video` for `model_family="minimax_h3_hyperflow_local"`, plus `checkpoint_name` and `loader` (`auto|official_int8|community_int8|gguf`).

- [ ] **Step 1: Write the failing test**

Append to `tests/contracts/test_narrative_workflow.py`:

```python
def test_hyperflow_t2v_binds_prompt_seed_dimensions_and_steps():
    tool = ComfyUIVideo()
    tool._client.is_available = lambda: True
    captured = {}

    def generate(workflow, output_node, dest, **kwargs):
        captured.update(workflow)
        Path(dest).write_bytes(b"result")
        return [Path(dest)]

    tool._client.generate = generate
    result = tool.execute({
        "prompt": "a wet alley", "seed": 7, "width": 960, "height": 544,
        "num_frames": 73, "steps": 6, "operation": "text_to_video",
        "model_family": "minimax_h3_hyperflow_local",
        "checkpoint_name": "minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors",
        "output_path": str(Path(tempfile.mkdtemp()) / "out.mp4"),
    })
    assert result.success, result.error
    assert captured["5"]["inputs"]["prompt"] == "a wet alley"
    assert captured["8"]["inputs"]["noise_seed"] == 7
    assert captured["5"]["inputs"]["width"] == 960
    assert captured["5"]["inputs"]["length"] == 73
    assert captured["6"]["inputs"]["steps"] == 6


def test_hyperflow_ref2v_binds_two_reference_images():
    tool = ComfyUIVideo()
    tool._client.is_available = lambda: True
    tool._client.upload_image = lambda path, name: "remote-" + Path(path).name
    captured = {}

    def generate(workflow, output_node, dest, **kwargs):
        captured.update(workflow)
        Path(dest).write_bytes(b"result")
        return [Path(dest)]

    tool._client.generate = generate
    tmp = Path(tempfile.mkdtemp())
    for name in ("hero.png", "place.png"):
        (tmp / name).write_bytes(b"image")
    result = tool.execute({
        "prompt": "hero in the alley", "operation": "reference_to_video",
        "model_family": "minimax_h3_hyperflow_local",
        "checkpoint_name": "minimax_h3_ref2va_hyperflow_flash_14b-int8_convrot.safetensors",
        "reference_image_paths": [str(tmp / "hero.png"), str(tmp / "place.png")],
        "output_path": str(tmp / "out.mp4"),
    })
    assert result.success, result.error
    assert captured["20"]["inputs"]["image"] == "remote-hero.png"
    assert captured["21"]["inputs"]["image"] == "remote-place.png"


def test_hyperflow_official_int8_switches_to_official_loader():
    tool = ComfyUIVideo()
    tool._client.is_available = lambda: True
    captured = {}

    def generate(workflow, output_node, dest, **kwargs):
        captured.update(workflow)
        Path(dest).write_bytes(b"result")
        return [Path(dest)]

    tool._client.generate = generate
    result = tool.execute({
        "prompt": "a wet alley", "operation": "text_to_video",
        "model_family": "minimax_h3_hyperflow_local",
        "checkpoint_name": "minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors",
        "loader": "auto",
        "output_path": str(Path(tempfile.mkdtemp()) / "out.mp4"),
    })
    assert result.success, result.error
    assert captured["1"]["class_type"] == "HyperFlowLoader"
    assert captured["1"]["inputs"]["unet_name"].endswith("14b-int8_convrot.safetensors")
    assert "patcher" not in captured["1"]["inputs"]


def test_hyperflow_gguf_switches_to_gguf_loader():
    tool = ComfyUIVideo()
    tool._client.is_available = lambda: True
    captured = {}

    def generate(workflow, output_node, dest, **kwargs):
        captured.update(workflow)
        Path(dest).write_bytes(b"result")
        return [Path(dest)]

    tool._client.generate = generate
    result = tool.execute({
        "prompt": "a wet alley", "operation": "text_to_video",
        "model_family": "minimax_h3_hyperflow_local",
        "checkpoint_name": "minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf",
        "loader": "auto",
        "output_path": str(Path(tempfile.mkdtemp()) / "out.mp4"),
    })
    assert result.success, result.error
    assert captured["1"]["class_type"] == "HyperFlowGGUFLoader"
    assert captured["1"]["inputs"]["unet_name"].endswith("Q4_K_M.gguf")
```

Add `import tempfile` at the top of the test module.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_narrative_workflow.py -v -k hyperflow`
Expected: FAIL; the operations are rejected or the workflow is not found.

- [ ] **Step 3: Implement**

- Extend the `operation` enum with `first_last_frame_to_video` and `reference_to_video`.
- Add input properties:
  - `steps`: integer enum `[4, 6, 8]`, default `6`.
  - `first_frame_image_path`, `last_frame_image_path`: strings.
  - `reference_image_paths`: array of strings, max 2.
  - `checkpoint_name`: string; the exact file in `diffusion_models/`.
  - `loader`: enum `auto|official_int8|community_int8|gguf`, default `auto`.
- Add module constants:
  ```python
  _HYPERFLOW_WORKFLOWS = {
      "text_to_video": "hyperflow_int8_t2v_api.json",
      "image_to_video": "hyperflow_int8_i2v_api.json",
      "first_last_frame_to_video": "hyperflow_int8_flf2v_api.json",
      "reference_to_video": "hyperflow_int8_ref2v_api.json",
  }
  _HYPERFLOW_OUTPUT_NODE = "14"
  ```
- Add `_normalize_hyperflow_loader(workflow, checkpoint_name, loader)` to patch node `1` because the bundled API workflows ship with the community loader and the BennyDaBall filenames:
  - `.gguf` or `loader="gguf"` → `class_type="HyperFlowGGUFLoader"`, inputs `{"unet_name": checkpoint_name, "weights_in": "auto"}`.
  - `"14b-int8_convrot"` in the name or `loader="official_int8"` → `class_type="HyperFlowLoader"`, inputs `{"unet_name": checkpoint_name}` (no `patcher`).
  - otherwise or `loader="community_int8"` → `class_type="HyperFlowINT8Loader"`, inputs `{"unet_name": checkpoint_name, "patcher": "legacy"}`.
- Add `_build_hyperflow(inputs, seed, output_path) -> tuple[dict, str, dict]`: load the workflow for the operation, normalize the loader, bind prompt to node `5` input `prompt`, seed to `8`/`noise_seed`, width/height/num_frames to `5`, steps to `6`/`steps`, and filename prefix to `14`/`filename_prefix`. For i2v bind `reference_image_path` to `20`/`image`; for flf2v bind first/last to `20`/`image` and `21`/`image`; for ref2v bind `reference_images.ref_image_0` to `20`/`image` and `ref_image_1` to `21`/`image`.
- Route this family through the existing custom-workflow execution path, uploading local images as the current code does.
- Validate: `reference_to_video` needs 2 `reference_image_paths`; `first_last_frame_to_video` needs both frame paths; a `checkpoint_name` is required when no `workflow_path`/`workflow_json` is supplied; raise `ValueError` before submitting.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_narrative_workflow.py -v -k hyperflow`
Expected: 2 passed (plus the existing tests stay green).

- [ ] **Step 5: Commit**

```bash
git add tools/video/comfyui_video.py tests/contracts/test_narrative_workflow.py
git commit -m "feat(comfyui): 支持 HyperFlow 的四种输入模式"
```

---

### Task 9.5: Close the HyperFlow selector and scanner gaps

**Why:** Task 9's review found two end-to-end gaps: the new operations are not reachable through `VideoSelector`, and the execute-example scanner reads the plan document itself, producing four false failures. This task closes both before the branch is reviewed.

**Files:**
- Modify: `tests/contracts/test_skill_execute_examples.py`
- Modify: `tools/video/comfyui_video.py`
- Modify: `tools/video/video_selector.py`
- Modify: `tests/contracts/test_comfyui_tools.py`
- Test: `tests/contracts/test_hyperflow_selector.py`

**Interfaces:**
- `ComfyUIVideo.supports` gains `first_last_frame_to_video: True` and `reference_to_video: True`.
- `operation_statuses()` returns all four operations; `is_operation_available()` accepts all four.
- `execute()` rejects `first_last_frame_to_video` / `reference_to_video` for any family other than `minimax_h3_hyperflow_local` before building a workflow.
- The doc scanner skips `docs/superpowers/plans/**`.

- [ ] **Step 1: Write the failing tests**

Create `tests/contracts/test_hyperflow_selector.py`:

```python
from tools.video.comfyui_video import ComfyUIVideo


def test_hyperflow_operations_are_advertised():
    tool = ComfyUIVideo()
    tool._client.is_available = lambda: True
    for operation in ("first_last_frame_to_video", "reference_to_video"):
        assert tool.supports.get(operation) is True
        assert operation in tool.operation_statuses()
        assert tool.is_operation_available(operation) is True


def test_non_hyperflow_family_rejects_new_operations():
    result = ComfyUIVideo().execute({
        "prompt": "x", "model_family": "wan2.2",
        "operation": "reference_to_video",
        "output_path": "out.mp4",
    })
    assert not result.success
    assert "minimax_h3_hyperflow_local" in (result.error or "")
```

Append to `tests/contracts/test_skill_execute_examples.py`:

```python
def test_plan_docs_are_not_scanned():
    assert not [where for where, _, _ in EXAMPLES if where.startswith("docs/superpowers/plans/")]
```

- [ ] **Step 2: Run them to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hyperflow_selector.py tests/contracts/test_skill_execute_examples.py -v`
Expected: the selector/guard tests fail; the plan-doc scan test fails.

- [ ] **Step 3: Implement**

- In `tools/video/comfyui_video.py`: add the two `supports` keys; extend `operation_statuses()` with `first_last_frame_to_video` and `reference_to_video` (`available` when the server is available and the corresponding `hyperflow_int8_*_api.json` exists, `degraded` otherwise); extend `is_operation_available()` to accept all four; add the family/operation guard at the top of `execute`.
- In `tools/video/video_selector.py`: no logic change is expected if it reads `supports`/`operation_statuses`; verify the new operations route. If a hardcoded operation set exists, extend it.
- In `tests/contracts/test_comfyui_tools.py`: update the exact-dict assertion for `operation_statuses()` to include the two new keys.
- In `tests/contracts/test_skill_execute_examples.py`: filter out paths whose repo-relative form starts with `docs/superpowers/plans/`.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hyperflow_selector.py tests/contracts/test_skill_execute_examples.py tests/contracts/test_comfyui_tools.py -v`
Expected: all pass; the four plan-doc false failures are gone.

- [ ] **Step 5: Commit**

```bash
git add tools/video/comfyui_video.py tools/video/video_selector.py tests/contracts/test_comfyui_tools.py tests/contracts/test_skill_execute_examples.py tests/contracts/test_hyperflow_selector.py
git commit -m "fix(comfyui): 打通 HyperFlow 选择器并排除计划文档扫描"
```

---

### Task 10: Add the model-neutral `shot_spec` schema

**Files:**
- Create: `schemas/artifacts/shot_spec.schema.json`
- Test: `tests/contracts/test_shot_spec_schema.py`

**Interfaces:**
- Produces: schema consumed by the scene/asset directors in Task 11 and by `artifacts/shot_specs.json`.
- No provider-specific keys are allowed.

- [ ] **Step 1: Write the failing test**

```python
import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/artifacts/shot_spec.schema.json").read_text(encoding="utf-8"))

SAMPLE = {
    "version": "1.0",
    "shots": [{
        "shot_id": "shot-01", "scene_id": "scene-01", "duration_seconds": 5,
        "scene_context": "Ron calls Adam from his office.",
        "references": [{"asset_id": "hero", "kind": "image", "path": "assets/references/hero.png", "role": "identity"}],
        "location_map": "Desk spans the frame; camera on Ron's right.",
        "first_frame": "Close-up of Ron's mouth and the receiver.",
        "format_mode": "single take, real time",
        "optics": "47-degree diagonal field of view",
        "camera": "tripod, slow push-in",
        "action_timing": "0-2s Ron speaks; 2-5s he slams the receiver.",
        "physics": "Receiver cable snaps taut; ash jumps.",
        "lighting": "Single banker's lamp, warm, from frame left.",
        "audio": "Room tone, receiver click, no music.",
        "character_acting": "Objective: force Adam to act. Obstacle: guilt.",
        "style": "Neo-noir, 35mm grain, anamorphic flare.",
        "quality": "Face and hands readable at key beats.",
        "constraints": "One character; no on-screen text.",
    }],
}


def test_complete_spec_is_valid():
    jsonschema.validate(SAMPLE, SCHEMA)


def test_provider_specific_field_is_rejected():
    bad = copy.deepcopy(SAMPLE)
    bad["shots"][0]["model_version"] = "2.5"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_shot_spec_schema.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the schema**

Top level: `version` const `"1.0"` and `shots` array. Each shot requires the 15 section keys (`scene_context`, `references`, `location_map`, `first_frame`, `format_mode`, `optics`, `camera`, `action_timing`, `physics`, `lighting`, `audio`, `character_acting`, `style`, `quality`, `constraints`) plus `shot_id`, `scene_id`, `duration_seconds` — 18 required keys in total. Set `additionalProperties: false` at both levels. `references` items require `asset_id`, `kind` (`image|video|audio`), `path`, `role`, with `additionalProperties: false`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_shot_spec_schema.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add schemas/artifacts/shot_spec.schema.json tests/contracts/test_shot_spec_schema.py
git commit -m "feat(schema): 增加模型无关的 shot_spec 规格"

---

### Task 10.5: Validate three-image character sheets

**Files:**
- Modify: `lib/narrative_assets.py`
- Test: `tests/lib/test_narrative_assets.py`

**Interfaces:**
- Produces: `validate_character_sheet(descriptor: str, sheet_paths: Sequence[str | Path]) -> None`.
- Consumes: filesystem paths already created by LIRA / image tools.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from lib.narrative_assets import validate_character_sheet


def test_character_sheet_requires_three_existing_images(tmp_path):
    paths = []
    for name in ("face.png", "front.png", "back.png"):
        path = tmp_path / name
        path.write_bytes(b"image")
        paths.append(path)
    validate_character_sheet("Hero, wet, white hair", paths)
    with pytest.raises(ValueError, match="exactly three"):
        validate_character_sheet("Hero", paths[:2])
    with pytest.raises(ValueError, match="missing"):
        validate_character_sheet("Hero", [*paths[:2], tmp_path / "missing.png"])
    with pytest.raises(ValueError, match="descriptor"):
        validate_character_sheet("", paths)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_narrative_assets.py -v -k character_sheet`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Add a module-level function in `lib/narrative_assets.py` that strips the descriptor, rejects an empty one, requires exactly three paths, and raises `ValueError` naming each missing file. It does not mutate the catalog.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/lib/test_narrative_assets.py -v -k character_sheet`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/narrative_assets.py tests/lib/test_narrative_assets.py
git commit -m "feat(narrative): 校验三联角色表与描述符"
```
```

---

### Task 11: Update the cinematic director skills

**Files:**
- Modify: `skills/pipelines/cinematic/proposal-director.md`
- Modify: `skills/pipelines/cinematic/scene-director.md`
- Modify: `skills/pipelines/cinematic/asset-director.md`
- Modify: `skills/pipelines/cinematic/edit-director.md`
- Modify: `skills/pipelines/cinematic/compose-director.md`
- Test: `tests/contracts/test_hell_grind_integration.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 5, and 10.
- Produces: stage instructions that call `video_model_selection`, `shot_spec`, and the asset gates.

- [ ] **Step 1: Write the failing test**

Append to `tests/contracts/test_hell_grind_integration.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "skills" / "pipelines" / "cinematic"


def test_proposal_presents_model_menu_and_logs_choice():
    text = (PIPELINE / "proposal-director.md").read_text(encoding="utf-8").lower()
    for phrase in ("video model shortlist", "local first", "provider_selection", "video model and route"):
        assert phrase in text


def test_asset_director_enforces_assets_then_model_then_takes():
    text = (PIPELINE / "asset-director.md").read_text(encoding="utf-8").lower()
    for phrase in ("asset sheets", "stress test", "360", "video character card", "model and route", "take budget"):
        assert phrase in text


def test_scene_director_names_required_assets_and_location_map():
    text = (PIPELINE / "scene-director.md").read_text(encoding="utf-8").lower()
    assert "required_assets" in text
    assert "location_map" in text


def test_edit_and_compose_cover_post_work():
    for name in ("edit-director.md", "compose-director.md"):
        text = (PIPELINE / name).read_text(encoding="utf-8").lower()
        for phrase in ("cleanup", "color", "sound"):
            assert phrase in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_integration.py -v -k director`
Expected: FAIL on the first missing phrase.

- [ ] **Step 3: Write the instructions**

- **proposal-director**: add a `## Video model shortlist` section. It reads `.agents/skills/hyperflow-h3`, `.agents/skills/minimax-h3`, and `skills/creative/video-model-selection.md`; calls `registry.discover()` then `lib.video_model_selection.build_menu`; when a local route is a candidate, calls `lib.local_video_readiness.check_hyperflow_readiness` and shows blockers; presents local routes first with status and 5-second cost; recommends one; waits for approval; writes the shortlist and selected route into `proposal_packet.metadata` (`video_model_shortlist`, `selected_route`) and records `provider_selection` / `Video model and route` with `record_selection`.
- **scene-director**: require each scene to carry `required_assets` (kind, descriptor, source) and a `location_map`; require a shot id per shot.
- **asset-director**: order the stage as asset sheets → stress test → optional 360° empty-scene sweep → video character card → model and route gate → shot specs → prompt compilation → batch takes → selection. State the 2–4 take budget and the rule that a failed stress test returns to asset design.
- **edit-director**: add Cleanup / Color / Sound sections with the Hell-Grind post rules (deflicker, grain match, grade per scene, dialogue/ambience/music balance).
- **compose-director**: reference the same three post passes before the final render; keep the existing render-runtime governance.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/contracts/test_hell_grind_integration.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skills/pipelines/cinematic/*.md tests/contracts/test_hell_grind_integration.py
git commit -m "docs(cinematic): 将资产与模型门禁写入阶段指令"
```

---

### Task 12: Add the ModelScope download script

**Files:**
- Create: `scripts/download_hyperflow_models.py`
- Test: `tests/scripts/test_download_hyperflow_models.py`

**Interfaces:**
- Produces: `python scripts/download_hyperflow_models.py --variant {gguf,int8} --dry-run` prints the exact `modelscope download` commands and total size; without `--accept-license`, a real run exits 2.
- Consumes: ModelScope repos `VideoRebirthAI/hyperflow-h3-flash` and `Comfy-Org/MiniMax-H3`.

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "download_hyperflow_models.py"


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_dry_run_lists_modelscope_sources_and_sizes():
    result = run("--variant", "gguf", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "VideoRebirthAI/hyperflow-h3-flash" in result.stdout
    assert "9.05 GB" in result.stdout and "9.22 GB" in result.stdout
    assert "Comfy-Org/MiniMax-H3" in result.stdout
    assert "1.99 GB" in result.stdout


def test_real_run_requires_license_acceptance():
    result = run("--variant", "gguf")
    assert result.returncode == 2
    assert "accept-license" in result.stderr.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/scripts/test_download_hyperflow_models.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Implement the script**

- Define `SOURCES = {"gguf": [...], "int8": [...]}` with `(repo, path, size_gb)` tuples exactly as in `docs/hell-grind-integration.md` 4.7.1, plus the sol VAE entry from `Comfy-Org/MiniMax-H3`.
- `--variant` defaults to `gguf`; `--dest` defaults to `G:/ComfyUI/Shared/downloads/hyperflow`.
- `--dry-run` prints one `modelscope download --model <repo> --include '<path>' --local_dir <dest>` line per file, then `Total: 20.26 GB`.
- Without `--accept-license`, print `Error: pass --accept-license to accept the MiniMax H3 Community License.` to stderr and return 2.
- With `--accept-license`, import `modelscope`; if missing, print `pip install modelscope` and return 2; otherwise run each download via `subprocess.run`.
- Do not move files automatically; print the move destinations.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scripts/test_download_hyperflow_models.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/download_hyperflow_models.py tests/scripts/test_download_hyperflow_models.py
git commit -m "feat(scripts): 增加 ModelScope 优先的 HyperFlow 下载脚本"
```

---

### Task 13: Local ComfyUI smoke test (operational)

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 3–9 and the downloaded models from Task 12.
- Produces: a `decision_log` entry proving the local route is usable.

- [ ] **Step 1: Install ModelScope and download INT8**

```bash
.venv/Scripts/python.exe -m pip install modelscope
.venv/Scripts/python.exe scripts/download_hyperflow_models.py --variant int8 --accept-license
```

Move `minimax_h3_fl2va_hyperflow_flash_int8_convrot.safetensors` and `minimax_h3_ref2va_hyperflow_flash_int8_convrot.safetensors` into `G:/ComfyUI/Shared/models/diffusion_models/`; move `minimax_h3_sol_vae_int8_convrot.safetensors` into `G:/ComfyUI/Shared/models/vae/`.

- [ ] **Step 2: Check readiness**

```bash
.venv/Scripts/python.exe -c "
from lib.local_video_readiness import check_hyperflow_readiness
print(check_hyperflow_readiness(r'G:/ComfyUI/Installs/ComfyUI/ComfyUI', [r'G:/ComfyUI/Shared/models'], server_running=False))
"
```

Expected: only the server blocker remains.

- [ ] **Step 3: Start ComfyUI and run a 5-second t2v**

Start the server with `comfy launch --background` (or the equivalent project command). Then run:

```bash
.venv/Scripts/python.exe -c "
from tools.video.comfyui_video import ComfyUIVideo
r = ComfyUIVideo().execute({
  'prompt': 'A rain-soaked neo-noir alley, one continuous shot, slow push-in.',
  'model_family': 'minimax_h3_hyperflow_local',
  'checkpoint_name': 'minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors',
  'loader': 'auto',
  'operation': 'text_to_video',
  'width': 960, 'height': 544, 'num_frames': 73, 'steps': 6,
  'output_path': 'projects/hyperflow-smoke/assets/video/t2v.mp4',
})
print(r.success, r.error, r.data.get('timing'))
"
```

Expected: `True`, an MP4 with one video and one audio stream, peak VRAM below 16 GB.

- [ ] **Step 4: If OOM, fall back**

Reduce to 640×352, 49 frames. If still OOM, download the GGUF variant and use the official `HyperFlowGGUFLoader` workflow exported to API format; record the change in `decision_log` with `category: "provider_selection"`, `subject: "Video model and route"`.

- [ ] **Step 5: Record the decision**

```bash
.venv/Scripts/python.exe -c "
from lib.video_model_selection import record_selection
record_selection('projects/hyperflow-smoke/decision_log.json', 'hyperflow-smoke', 'assets',
  {'route_id': 'hyperflow_int8'},
  [{'option_id':'hyperflow_int8','label':'HyperFlow INT8','score':1.0,'reason':'local first'}],
  'Local smoke test passed at 960x544, 73 frames, 6 steps.')
"
```

- [ ] **Step 6: Commit the smoke report**

Write `docs/superpowers/plans/artifacts/2026-11-19-hyperflow-smoke.md` with the command, output path, ffprobe summary, timing, and peak VRAM; commit it.

---

### Task 14: Pilot one Hell-Grind scene (operational, after Task 13)

**Files:** project workspace only.

- [ ] **Step 1: Pick a small scene** from the Hell-Grind archive (for example `Scene 73.6`, 12 prompts) and initialize a project with `lib.checkpoint.init_project`.
- [ ] **Step 2: Run `research → proposal → script → scene_plan`** using the cinematic pipeline. At proposal, present the model menu and record the user's choice.
- [ ] **Step 3: Produce asset sheets** for one character and one location; pass the stress test; get user approval.
- [ ] **Step 4: Write one `shot_spec`** matching the schema, compile it to the H3 prompt, and generate 2 takes locally.
- [ ] **Step 5: Select the better take**, export `asset_manifest`, and run edit/compose on FFmpeg.
- [ ] **Step 6: Record** wall time, peak VRAM, adoption ratio, and output path in `docs/superpowers/plans/artifacts/2026-11-19-pilot-scene.md`.

---

### Optional Task 15: Hell-Grind prompt corpus index (P2)

**Files:**
- Create: `scripts/hell_grind_prompt_index.py`
- Test: `tests/scripts/test_hell_grind_prompt_index.py`

- [ ] **Step 1: Write the failing test** with a tmp tree containing `folders/Scene 1/prompts/00001_abc.txt`, its `.json`, and `.zh.md`; assert the script emits one JSONL record with `scene`, `prompt_path`, `job_set_id`, `job_type`, `prompt`, and `zh_path`.
- [ ] **Step 2: Run it; expect failure.**
- [ ] **Step 3: Implement** `--source`, `--output`, skipping media and empty prompts; parse `job_set_id` and `job_type` from the `.json` metadata.
- [ ] **Step 4: Run it; expect pass.** Never copy media; output stays under `reference/hell-grind/`.
- [ ] **Step 5: Commit** `feat(corpus): 增加 Hell-Grind 提示词索引脚本`.
