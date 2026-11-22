# MiniMax H3 Project RefMods Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make project-scoped RefMods the default conditioning path for reusable, approved assets in local MiniMax H3 cinematic shot generation.

**Architecture:** Add a `ComfyUIRefMod` tool to extract approved reference assets into project-scoped `.safetensors` files, with loader-visible copies under the ComfyUI RefMod model folder. Persist the source mapping and hashes in the asset manifest, then bind only each shot's relevant Mods into a local H3 Ref2VA workflow. Exact FL2VA first/last-frame shots remain native, and hosted H3 routes remain unchanged.

**Tech Stack:** Python `BaseTool`, OpenMontage `ComfyUIClient`, ComfyUI API workflows and the installed `ComfyUI-MiniMaxH3Mod` nodes, JSON Schema, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-minimax-h3-refmod-default-design.md`

## Global Constraints

- Extract Mods only from `asset_sheets`-approved images; source changes invalidate dependent Mods.
- Canonical `.safetensors` files live under `projects/<project_id>/assets/refmods/`; loader-visible copies use `models/refmods/openmontage/<project_id>/`.
- Each Mod is keyed by the approved source `asset_id` and state; a shot uses only Mods for its referenced assets.
- Only local MiniMax H3 Ref2VA workflows apply RefMods. Hosted H3, other providers, and model-family decisions remain unchanged.
- Exact first/last-frame shots remain on native FL2VA. If a shot requests both RefMod and exact first/last frames, stop for an explicit choice; do not change the operation silently.
- `MiniMaxH3RefModsLoader` exposes eight slots. Group larger sets through chained loader/apply nodes in stable order; never silently truncate.
- Never load a shared RefMod just because its filename resembles a project asset. Never overwrite another project or the existing `测试人001` Mod.
- If the live ComfyUI target lacks required H3/RefMod nodes or models, block before the batch and surface the compatible native H3 path for explicit user choice.
- Preserve the user's current checkout and all pre-existing uncommitted RelayVSR changes. Stage only this plan's files/hunks; use patch staging for `asset_manifest.schema.json`, `asset-director.md`, and `comfyui_video.py`.
- Use `.\.venv\Scripts\python.exe -m pytest`; the system Python does not provide project test dependencies.
- The current whole-suite baseline has five `test_showcase_card_security.py` failures caused by the selected FFmpeg build's missing Fontconfig configuration; report them separately from RefMod tests.

## Review Focus

- An approved source image changes after extraction: the prior Mod is rejected or rebuilt before generation, and the manifest does not advertise it as current — test in Tasks 1, 2, and 4.
- A character or prop has multiple state variants: a shot receives the matching state Mod only, even when variants share an `entity_id` — test in Tasks 1, 3, and 4.
- A shot combines RefMods with an existing native motion/video reference: prompt labels and final Ref2VA order remain exact, without duplicate identity references — test in Tasks 3 and 4.
- The live ComfyUI endpoint, RefMod pack, or H3 model stack is stale or unavailable: preparation blocks before generation and does not silently fall back — test in Tasks 2 and 4.
- The route is hosted MiniMax H3, another provider, an exact FL2VA first/last-frame operation, or an existing project with no opt-in: it keeps its approved path — test in Tasks 3 and 4.

---

### Task 1: Persist Project RefMod Provenance

**Files:**
- Modify: `schemas/artifacts/asset_manifest.schema.json`
- Modify: `lib/narrative_assets.py`
- Add: `docs/superpowers/plans/2026-11-22-minimax-h3-refmod-default.md`
- Create: `tests/contracts/test_narrative_refmod_schemas.py`
- Modify: `tests/lib/test_narrative_assets.py`

**Interfaces:**
- Add `NarrativeAssets.register_refmod_asset(asset_id: str, *, project_path: str, loader_name: str, concept_type: str, extractor: Mapping[str, Any]) -> None`.
- Add `NarrativeAssets.record_refmod_usage(mode: Literal["project_refmod", "native_ref2va"], *, route_id: str, decision_id: str) -> None`; export the selected mode, H3 route, and decision ID under `asset_manifest.metadata.refmod_usage`.
- Require an existing approved asset record with an `entity_id`, `state`, and project-relative image path. Derive `source_sha256` from that path, verify the canonical Mod is inside the project, reject loader-name traversal, and record `refmod_sha256` from the Mod file.
- Export `asset_manifest()["metadata"]["refmod_assets"]`, keyed by source `asset_id`, with `entity_id`, `state`, `concept_type`, `project_path`, `loader_name`, `source_path`, `source_sha256`, `refmod_sha256`, `status` (`ready` or `stale`), and `extractor` provenance.
- Add `NarrativeAssets.refmods_for_shot(shot_id: str) -> list[dict[str, Any]]`, returning only current Mod records for the shot's linked assets in stable `asset_id` order. Each row includes `asset_id`, `entity_id`, `state`, `loader_name`, `concept_type`, `description`, and deterministic `<Subject N>` `prompt_label` values. Omit stale source/Mod hashes and unrelated catalog assets.

- [ ] **Step 1: Write failing schema and catalog tests** with these names and assertions:

```python
def test_asset_manifest_exports_refmod_provenance(tmp_path):
    assert manifest["metadata"]["refmod_assets"]["hero-wet"]["entity_id"] == "hero"
    assert manifest["metadata"]["refmod_assets"]["hero-wet"]["source_sha256"] == expected_sha256
    assert manifest["metadata"]["refmod_assets"]["hero-wet"]["status"] == "ready"

def test_asset_manifest_exports_refmod_usage_decision(tmp_path):
    catalog.record_refmod_usage("project_refmod", route_id="minimax_h3_local", decision_id="d-004")
    assert catalog.asset_manifest()["metadata"]["refmod_usage"] == {
        "mode": "project_refmod",
        "route_id": "minimax_h3_local",
        "decision_id": "d-004",
    }

def test_refmod_registration_rejects_outside_project_and_loader_traversal(tmp_path):
    with pytest.raises(ValueError, match="project"):
        catalog.register_refmod_asset("hero-wet", project_path=str(outside), loader_name="../foreign/mod", ...)

def test_refmods_for_shot_returns_only_current_linked_assets(tmp_path):
    refs = catalog.refmods_for_shot("s01-sh01")
    assert [item["asset_id"] for item in refs] == ["hero-wet"]
    assert refs[0]["prompt_label"] == "<Subject 1>"

def test_refmods_for_shot_skips_changed_source_hash(tmp_path):
    assert catalog.refmods_for_shot("s01-sh01") == []
    assert catalog.asset_manifest()["metadata"]["refmod_assets"]["hero-wet"]["status"] == "stale"

def test_legacy_asset_manifest_without_refmod_metadata_still_validates():
    validate_artifact("asset_manifest", legacy_manifest)
```

- [ ] **Step 2: Run the tests and confirm the new contract is missing.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_refmod_schemas.py tests/lib/test_narrative_assets.py -q`

Expected: the new RefMod schema/catalog cases fail while existing narrative asset tests pass.

- [ ] **Step 3: Add `metadata.refmod_assets` to the schema and implement `register_refmod_asset` / `refmods_for_shot`.** Recompute the current source hash when exporting; stale Mods must be absent from shot-ready mappings.
- [ ] **Step 4: Run the schema and catalog tests.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_refmod_schemas.py tests/lib/test_narrative_assets.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the manifest contract and catalog.** Stage only this plan's schema hunk because the schema file also contains an existing RelayVSR edit.

```powershell
git add docs/superpowers/plans/2026-11-22-minimax-h3-refmod-default.md lib/narrative_assets.py tests/contracts/test_narrative_refmod_schemas.py tests/lib/test_narrative_assets.py
git add -p schemas/artifacts/asset_manifest.schema.json
git diff --cached --check
git commit -m "feat: persist project MiniMax H3 RefMods"
```

### Task 2: Extract RefMods as Project Assets

**Files:**
- Create: `tools/video/comfyui_refmod.py`
- Create: `tools/_comfyui/workflows/refmod_extract_api.json`
- Test: `tests/contracts/test_comfyui_refmod.py`
- Test: `tests/lib/test_comfyui_refmod_paths.py`

**Interfaces:**
- Register `ComfyUIRefMod` as a `BaseTool` named `comfyui_refmod`, provider `comfyui`, capability `asset_conditioning`, runtime `LOCAL_GPU`.
- Its `extract` operation accepts `project_id`, `project_dir`, `comfyui_workspace`, `server_url`, `asset_id`, the catalog's `reference_path`, the approved H3 `video_vae_name`, and `concept_type`; it verifies that `reference_path` is exactly the approved catalog path and returns `project_path`, `loader_name`, source/Mod hashes, extraction metadata, and the ComfyUI prompt ID.
- Set `idempotency_key_fields` to include `project_id`, `asset_id`, `reference_path`, `concept_type`, `video_vae_name`, and `server_url`. The file-valued `reference_path` must be content-fingerprinted so source edits cannot reuse a cached Mod.
- Use a deterministic name under `openmontage/<project_id>/` that includes a source hash. Reuse an existing Mod only when source and Mod hashes both match.
- Default extraction mode to the live node's `Compressed Reference` preset. Map `character` to `identity`, `location` to `background`, and `prop` to `generic`; preserve an explicit `clothing` or `style` override.
- Record the RefMod node-pack version and selected H3 video VAE in `extractor.model_stack`; include both in the deterministic loader-name signature so a node/VAE update cannot reuse an incompatible Mod.
- Validate that the ComfyUI target is local/shared-storage, the approved source is inside the project, and the live `object_info` exposes `MiniMaxH3RefModExtract` and the selected H3 VAE. Bind `video_vae_name` into the bundled API workflow, copy the saved Mod into the project asset path, and register it through `NarrativeAssets.register_refmod_asset`.

- [ ] **Step 1: Write failing extraction tests** with these names and assertions:

```python
def test_refmod_extract_writes_project_asset_and_loader_copy(tmp_path, fake_comfy):
    assert Path(result.data["project_path"]).as_posix().startswith("assets/refmods/")
    assert result.data["loader_name"].startswith("openmontage/project-a/")
    assert sha256_file(project_path) == result.data["refmod_sha256"]

def test_refmod_extract_reuses_matching_source_hash(tmp_path, fake_comfy):
    assert second.data["from_cache"] is True
    assert fake_comfy.submission_count == 1

def test_refmod_extract_uses_new_name_after_source_change(tmp_path, fake_comfy):
    assert second.data["loader_name"] != first.data["loader_name"]

def test_refmod_extract_blocks_when_live_node_is_missing(tmp_path, fake_comfy):
    assert not result.success
    assert "MiniMaxH3RefModExtract" in result.error

def test_refmod_extract_rejects_unshared_remote_workspace(tmp_path, fake_comfy):
    assert not result.success
    assert "local" in result.error.lower() or "shared" in result.error.lower()
```

- [ ] **Step 2: Run those tests and confirm the tool/workflow is missing.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_comfyui_refmod.py tests/lib/test_comfyui_refmod_paths.py -q`

Expected: new RefMod tests fail; existing ComfyUI tests remain unchanged.

- [ ] **Step 3: Implement `ComfyUIRefMod` and the API extraction workflow.** Submit and poll through `ComfyUIClient`, parse the extraction node's saved path, verify the file exists, and never install or update third-party nodes automatically.
- [ ] **Step 4: Run extraction-tool and client tests.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_comfyui_refmod.py tests/lib/test_comfyui_refmod_paths.py tests/tools/test_comfyui_client_upload.py -q`

Expected: PASS; failed server/node checks return a clear blocked result without writing a Mod.

- [ ] **Step 5: Commit the extraction tool.**

```powershell
git add docs/superpowers/plans/2026-11-22-minimax-h3-refmod-default.md tools/video/comfyui_refmod.py tools/_comfyui/workflows/refmod_extract_api.json tests/contracts/test_comfyui_refmod.py tests/lib/test_comfyui_refmod_paths.py
git diff --cached --check
git commit -m "feat: extract project-scoped MiniMax H3 RefMods"
```

### Task 3: Apply Per-Shot RefMods to Local H3 Ref2VA

**Files:**
- Modify: `tools/video/comfyui_video.py`
- Create: `tools/_comfyui/refmod_workflow.py`
- Create: `tools/_comfyui/workflows/hyperflow_int8_ref2v_refmod_api.json`
- Modify: `tests/contracts/test_comfyui_tools.py`
- Create: `tests/contracts/test_comfyui_refmod_workflow.py`

**Interfaces:**
- Add optional `refmod_assets: list[dict[str, str]]` to local H3 execution. Each item contains `asset_id`, `loader_name`, `concept_type`, `state`, `description`, and `prompt_label`.
- Add optional `server_url: str` to `ComfyUIVideo.execute`. When present, construct a per-call `ComfyUIClient(server_url=server_url, capability="video")` and pass it to graph binding/upload/submission; do not mutate process-wide environment or shared client state.
- Add `build_refmod_workflow(workflow: dict[str, Any], refs: list[dict[str, str]], operation: str) -> tuple[dict[str, Any], list[str]]` in `tools/_comfyui/refmod_workflow.py`. It binds existing RefMod loader/apply nodes or safely injects them into a validated local H3 Ref2VA graph; it returns the modified API graph plus the exact ordered asset IDs.
- For `reference_to_video`, non-empty `refmod_assets` satisfy the visual-reference requirement, so zero or more native stills may accompany them. Preserve the existing two-native-image minimum when no RefMods are supplied.
- Apply Mods only to `reference_to_video` Ref2VA workflows. Exact `first_last_frame_to_video` remains FL2VA; if a shot requests both FL2VA and RefMods, return an explicit incompatibility error before submission.
- Keep native motion/video references and RefMods in one deterministic order, emit corresponding `<Subject N>` / `<Picture N>` labels from that same order, and chain loader/apply groups when more than eight Mods are referenced.
- For custom H3 graphs, accept an existing RefMod chain only when its node classes and connections validate; otherwise return an explicit RefMod workflow error instead of using native conditioning silently.
- When no Mods are present, keep the existing workflow unchanged. Hosted H3 and other model families reject accidentally supplied local RefMod bindings instead of silently ignoring them.

- [ ] **Step 1: Write failing graph tests** with these names and assertions:

```python
def test_refmod_only_reference_to_video_needs_no_native_stills():
    workflow, ordered_asset_ids = build_refmod_workflow(reference_to_video_workflow, refs=[mod("hero-wet")], operation="reference_to_video")
    assert ordered_asset_ids == ["hero-wet"]
    assert workflow["refmod_loader_1"]["inputs"]["mod_1"] == "openmontage/project-a/hero-wet"

def test_refmod_graph_keeps_native_motion_inputs_and_prompt_order():
    workflow, ordered_asset_ids = build_refmod_workflow(reference_to_video_workflow, refs=[mod("hero-wet"), mod("loc-master")], operation="reference_to_video")
    assert workflow["video_ref_loader"]["inputs"]["video"] == original_video_connection
    assert ordered_asset_ids == ["hero-wet", "loc-master"]
    assert [ref["prompt_label"] for ref in shot_refmods] == ["<Subject 1>", "<Subject 2>"]

def test_refmod_graph_chains_more_than_eight_mods_without_truncation():
    workflow, ordered_asset_ids = build_refmod_workflow(reference_to_video_workflow, refs=nine_mods, operation="reference_to_video")
    assert ordered_asset_ids == [f"asset-{i}" for i in range(9)]
    assert workflow["refmod_loader_2"]["inputs"]["mod_1"] == "openmontage/project-a/asset-8"
    assert workflow["refmod_apply_2"]["inputs"]["conditioning"] == ["refmod_apply_1", 0]

def test_fl2va_keyframe_operation_rejects_refmods():
    with pytest.raises(ValueError, match="FL2VA"):
        build_refmod_workflow(fl2v_workflow, refs=[mod("hero")], operation="first_last_frame_to_video")

def test_hosted_h3_route_rejects_local_refmods():
    assert "local RefMod" in result.error

def test_comfyui_video_uses_explicit_server_url(tmp_path, monkeypatch):
    assert submitted_client.server_url == "http://127.0.0.1:8290"

def test_custom_h3_graph_without_ref2va_conditioning_is_blocked():
    assert not result.success
    assert "Ref2VA conditioning" in result.error
```

- [ ] **Step 2: Run the new tests and confirm RefMod workflow binding is absent.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_comfyui_refmod_workflow.py tests/contracts/test_comfyui_tools.py -q`

Expected: new RefMod cases fail; existing native H3 workflow tests pass.

- [ ] **Step 3: Add the RefMod-aware Ref2VA API graph and implement the graph-binding helper.** Validate exactly one supported conditioning source and fail with the missing node/input in the error when a custom workflow is incompatible.
- [ ] **Step 4: Bind per-shot RefMods in `ComfyUIVideo` and include the mapping and hashes in workflow provenance.** Stage only the H3-related hunks from `comfyui_video.py` because that file contains an existing RelayVSR edit.
- [ ] **Step 5: Run the focused H3 tests.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_comfyui_refmod_workflow.py tests/contracts/test_comfyui_tools.py tests/contracts/test_narrative_workflow.py -q`

Expected: PASS; native operations, partner routes, and legacy custom workflows remain unchanged.

- [ ] **Step 6: Commit the H3 RefMod workflow.**

```powershell
git add tools/_comfyui/refmod_workflow.py tools/_comfyui/workflows/hyperflow_int8_ref2v_refmod_api.json tests/contracts/test_comfyui_refmod_workflow.py tests/contracts/test_comfyui_tools.py
git add -p tools/video/comfyui_video.py
git diff --cached --check
git commit -m "feat: apply project RefMods to local H3 shots"
```

### Task 4: Wire RefMods Into the Cinematic Asset Stage

**Files:**
- Modify: `pipeline_defs/cinematic.yaml`
- Modify: `skills/pipelines/cinematic/asset-director.md`
- Modify: `.agents/skills/minimax-h3/SKILL.md`
- Modify: `docs/narrative-production.md`
- Modify: `lib/video_model_selection.py`
- Modify: `schemas/artifacts/decision_log.schema.json`
- Test: `tests/contracts/test_narrative_cinematic.py`
- Create: `tests/contracts/test_narrative_refmod_decisions.py`
- Test: `tests/contracts/test_hell_grind_integration.py`
- Modify: `tests/lib/test_video_model_selection.py`
- Create: `tests/contracts/test_narrative_refmod_workflow.py`
- Modify: `tests/contracts/test_narrative_workflow.py`

**Interfaces:**
- After approved `asset_sheets` and local H3 `model_selection`, the asset director calls `comfyui_refmod` once per eligible approved asset/state before `Batch takes` and registers each result in `NarrativeAssets`.
- Eligible assets are approved character, clothing/state, location, or prop records referenced by at least one planned local H3 shot; current shot count does not affect eligibility.
- For each local H3 shot, pass `NarrativeAssets.refmods_for_shot(shot_id)` into `comfyui_video` and compile `subject_definitions` from the returned descriptors and labels.
- Before the local batch, read the selected ComfyUI target with the live `server_info` tool when available. Pass the same `server_url` to extraction and H3 generation and `workspace.path` to extraction; if unavailable, use the configured URL only after its `object_info` validates.
- Add `reference_conditioning_selection` to the decision-log category enum. Record the default `project_refmod` choice against subject `MiniMax H3 reusable-asset conditioning`, with `native_ref2va` retained as the considered option; append a new decision with the same category/subject when the user overrides it.
- Add `record_reference_conditioning_selection(path: str | Path, project_id: str, stage: str, mode: Literal["project_refmod", "native_ref2va"], options: Sequence[Mapping[str, Any]], reason: str) -> dict[str, Any]` in `lib/video_model_selection.py`. It appends an approved, latest-wins decision with the category/subject above, validates the decision-log schema, and writes atomically.
- After logging the decision, call `NarrativeAssets.record_refmod_usage` with the returned `decision_id` so the approved asset manifest and decision log show the same conditioning choice.
- Add optional `server_url: str | None` to `lib.video_model_selection.build_menu(...)`. For H3 local/HyperFlow routes only, use the supplied live server URL to verify the ComfyUI connection; keep other ComfyUI routes' existing readiness checks unchanged.
- Add `comfyui_refmod` to cinematic asset-stage availability. Keep `asset_sheets`, `model_selection`, and `enhancement_selection` gates unchanged; do not add a provider/model switch.
- Before local H3 model selection/extraction/generation, call ComfyUI `server_info` when available and pass the same live `server.url` to `build_menu`, `comfyui_refmod`, and `comfyui_video`, plus `workspace.path` to extraction. If the selected server workspace is not shared/accessible, block before the batch.
- For hosted H3, other providers, or exact FL2VA first/last-frame operations, do not send RefMod bindings. If a local RefMod prerequisite fails, block and offer the compatible native H3 path for explicit user choice.

- [ ] **Step 1: Write failing contract and pilot tests** with these assertions:

```python
def test_record_reference_conditioning_selection_appends_latest_mode(tmp_path):
    decision = record_reference_conditioning_selection(
        path, "film", "assets", "native_ref2va", OPTIONS, "The user chose native FL2VA keyframes for this shot."
    )
    assert decision["category"] == "reference_conditioning_selection"
    assert decision["subject"] == "MiniMax H3 reusable-asset conditioning"
    assert decision["selected"] == "native_ref2va"

def test_video_menu_uses_explicit_server_for_local_h3_only(monkeypatch):
    menu = build_menu(registry, server_url="http://127.0.0.1:8290")
    assert route(menu, "h3_local")["available"] is True
    assert route(menu, "hyperflow_int8")["available"] is True
    assert route(menu, "wan22")["available"] is False

def test_local_h3_pilot_persists_and_applies_project_refmods(tmp_path):
    assert manifest["metadata"]["refmod_assets"]["hero-wet"]["state"] == "wet"
    assert result.data["workflow_provenance"]["refmod_asset_ids"] == ["hero-wet", "loc-master"]

def test_stale_source_refmod_blocks_before_batch(tmp_path):
    assert not result.success
    assert "stale RefMod" in result.error

def test_fl2va_keyframes_do_not_receive_refmods(tmp_path):
    assert result.data["operation"] == "first_last_frame_to_video"
    assert result.data["workflow_provenance"].get("refmod_asset_ids", []) == []

def test_hosted_h3_keeps_native_provider_path(tmp_path):
    assert result.data["hosted"] is True
    assert result.data["workflow_provenance"]["source"] == "comfyui_partner_node"
    assert result.data["workflow_provenance"].get("refmod_asset_ids", []) == []

def test_refmod_extraction_and_h3_menu_and_batch_use_the_same_comfy_target(tmp_path):
    assert extraction.server_url == batch.server_url == "http://127.0.0.1:8290"
    assert h3_menu.server_url == "http://127.0.0.1:8290"
    assert extraction.workspace_path == "G:/ComfyUI/Installs/ComfyUI/ComfyUI"
```

- [ ] **Step 2: Run the tests and confirm current pipeline instructions do not wire RefMod.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_cinematic.py tests/contracts/test_narrative_refmod_decisions.py tests/contracts/test_hell_grind_integration.py tests/contracts/test_narrative_refmod_workflow.py tests/lib/test_video_model_selection.py -q`

Expected: new RefMod wiring assertions fail while existing cinematic approval sub-stages remain green.

- [ ] **Step 3: Implement `record_reference_conditioning_selection` and wire `comfyui_refmod` after both required approvals.** Update the asset director, H3 skill, and narrative production guide to record the decision pair and FL2VA incompatibility.
- [ ] **Step 4: Add the decision-log category and run the full relevant contract set.**

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_refmod_schemas.py tests/contracts/test_comfyui_refmod.py tests/contracts/test_comfyui_refmod_workflow.py tests/contracts/test_narrative_refmod_workflow.py tests/contracts/test_narrative_refmod_decisions.py tests/contracts/test_narrative_cinematic.py tests/contracts/test_narrative_workflow.py tests/contracts/test_comfyui_tools.py tests/lib/test_comfyui_refmod_paths.py tests/lib/test_narrative_assets.py tests/lib/test_video_model_selection.py -q`

Expected: PASS; legacy H3, source-led behavior, and hosted provider routes remain unchanged.

- [ ] **Step 5: Run the project suite and record the known Fontconfig failures separately.**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q`

Expected: all RefMod and narrative tests pass. The host's five existing `test_showcase_card_security.py` FFmpeg/Fontconfig failures may remain; do not modify that unrelated workflow in this plan.

- [ ] **Step 6: Commit the pipeline, integration tests, and documentation changes.** Stage only RefMod hunks from `asset-director.md`.

```powershell
git add pipeline_defs/cinematic.yaml .agents/skills/minimax-h3/SKILL.md docs/narrative-production.md lib/video_model_selection.py schemas/artifacts/decision_log.schema.json tests/contracts/test_narrative_cinematic.py tests/contracts/test_narrative_refmod_decisions.py tests/contracts/test_hell_grind_integration.py tests/contracts/test_narrative_refmod_workflow.py tests/contracts/test_narrative_workflow.py tests/lib/test_video_model_selection.py
git add -p skills/pipelines/cinematic/asset-director.md
git diff --cached --check
git commit -m "feat: default local H3 assets to project RefMods"
```

## Self-Review

- **Spec coverage:** Project isolation, approved-source extraction, per-shot application, native motion and keyframe references, hosted route preservation, endpoint readiness, decision logging, and stale-asset invalidation map to Tasks 1–4.
- **Step scan:** Each task has RED→GREEN tests, exact affected files, interfaces, a verification command, and a focused commit.
- **Type consistency:** `asset_id`, `entity_id`, `state`, `loader_name`, `project_path`, `source_sha256`, `refmod_sha256`, and `refmod_assets` are consistent across the catalog, schema, tool, workflow, and director.
- **Review Focus:** All five user-facing failure classes map to tests in the tasks that own their code.
- **Proportion:** Asset persistence, extraction, H3 graph binding, and pipeline wiring are independently testable units of one local H3 feature.

## Execution Note

The user previously chose Native execution and the current checkout. Preserve all pre-existing uncommitted RelayVSR edits and stage only this plan's hunks. The approved design changes conditioning only; it does not change provider/model routes. Exact FL2VA frame tasks remain native and cannot receive RefMods.
