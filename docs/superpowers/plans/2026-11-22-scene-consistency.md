# Narrative Scene Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce continuity contracts for characters, locations, props, and state transitions in new or opted-in cinematic `narrative_generated` projects.

**Architecture:** Extend the existing scene and shot artifacts with typed continuity data, then persist scene identity and review evidence in `NarrativeAssets`. A new model-neutral library validates plans and assembles per-shot reference context; cinematic stage skills call it before video generation. `VideoCompose` verifies that each strict-mode selected take has current review evidence before rendering.

**Tech Stack:** Python 3, JSON Schema draft 2020-12, pytest, OpenMontage stage skills and pipeline manifests.

**Spec:** `docs/superpowers/specs/2026-11-22-scene-consistency-design.md`

## Global Constraints

- Scope is `pipeline_defs/cinematic.yaml` production mode `narrative_generated`; source-led and other pipelines remain unchanged.
- `scene_plan.metadata.location_map` remains an optional object whose values are non-empty strings; `scene_plan.metadata.scene_continuity` remains optional in the schema so legacy scene plans validate.
- `proposal_packet.metadata.continuity_contract_version` value `"1.0"` enables strict mode; a missing value means legacy mode.
- New narrative-generated projects default to strict mode; existing projects stay in legacy mode unless the user opts in through the approved proposal stage and a `decision_log` `approval_policy` entry with subject `Scene continuity contract version`.
- Validate scene structure before reference-sheet/plate generation; validate shot specs and approved references after the `asset_sheets` gate and before video-shot generation.
- Track each character/prop state from its last appearance, including nonadjacent shots; location geometry and lighting reset according to each new scene's contract.
- Require a separate approved reference for visually salient state that persists across shots; represent transient one-shot state in shot data.
- A `drift` or `unclear` review is blocked by default and needs an explicit user override reason before selection.
- Review evidence is tied to the current selected media path; changing a take through enhancement makes its prior review stale.
- Preserve existing provider/model/runtime decisions, human approval gates, and project artifact paths. Do not add a default 3D route or make automatic visual scores blocking.
- Preserve existing project compatibility: old catalog entries without `scene_id` are read as `scene_id = shot_id`; old shots without a contract version remain legacy.
- Before implementation, inspect `git status --short` and preserve the user's existing unrelated changes.

## Review Focus

- Legacy proposal/catalog data without continuity markers remains readable and does not acquire strict review requirements — test in Tasks 1, 2, and 5.
- Multiple shots in one scene keep a shared `scene_id` and unique `shot_id` through catalog and manifest export — test in Task 2.
- A recurring entity's last state is checked after intervening shots/scenes where it is absent; explicit transitions pass — test in Task 3.
- Missing, mismatched, or outside-project reference assets stop strict video-shot generation before provider calls — test in Tasks 3 and 4.
- Enhancement cannot leave a selected take with stale review evidence; legacy takes continue through the compose guard — test in Task 5.

---

## File Map

- Modify `schemas/artifacts/proposal_packet.schema.json` to define the optional strict-mode version marker.
- Modify `schemas/artifacts/scene_plan.schema.json` and `schemas/artifacts/shot_spec.schema.json` to define scene- and shot-level continuity contracts while accepting legacy artifacts.
- Modify `schemas/artifacts/asset_manifest.schema.json` to validate exported continuity-shot and review metadata.
- Modify `lib/narrative_assets.py` to track scene IDs, entity IDs, contract versions, and review evidence; preserve the existing selected-take API.
- Create `lib/narrative_continuity.py` for strict/legacy mode resolution, pre-generation validation, last-appearance state checks, and model-neutral shot context assembly.
- Modify `tools/video/video_compose.py` to reject strict selections without current, approved review evidence.
- Update `skills/pipelines/cinematic/{proposal,scene,asset}-director.md`, `skills/creative/narrative-consistency.md`, and `docs/narrative-production.md` to define the workflow and its gates.
- Modify `pipeline_defs/cinematic.yaml` only to make the continuity review focus explicit for strict narrative assets; retain the existing approval sub-stages.
- Add or update focused tests under `tests/contracts/` and `tests/lib/` for schema, catalog, validator, stage-order, enhancement, and compose behavior.

## Task 1: Define Backward-Compatible Artifact Contracts

**Files:**
- Create: `docs/superpowers/specs/2026-11-22-scene-consistency-design.md`
- Create: `docs/superpowers/plans/2026-11-22-scene-consistency.md`
- Modify: `schemas/artifacts/proposal_packet.schema.json`
- Modify: `schemas/artifacts/scene_plan.schema.json`
- Modify: `schemas/artifacts/shot_spec.schema.json`
- Create: `tests/contracts/test_narrative_continuity_schemas.py`

**Interfaces:**
- Proposal metadata may contain `continuity_contract_version: "1.0"`; absence means legacy.
- `scene_plan.metadata.scene_continuity` is an object keyed by scene ID. Each value contains `location_id`, `master_angle`, `camera_axis`, `anchors[]` (`id`, `position`), `lighting` (`key_source`, `direction`, `shadow_direction`), optional `constants` (`time_of_day`, `weather`, `palette`), and `allowed_changes[]`.
- Keep `scene_plan.metadata.location_map[scene_id]` as a non-empty, human-readable summary derived from that typed contract; the strict validator checks both maps cover the same scenes and describe the same location.
- A shot's optional `continuity` object contains `contract_version`, `location_id`, nullable `previous_shot_id`, `entities[]` (`entity_id`, `asset_id`, `state`), `carried_states[]`, `intentional_changes[]` (`entity_id`, `from_state`, `to_state`, `reason`), `screen_direction`, `gaze_targets[]`, and `hand_prop_states[]`.
- Schema presence is backward-compatible; strict-mode completeness and cross-artifact links are enforced in Task 3.

- [ ] **Step 1: Write schema tests** with these names and assertions:

```python
def test_continuity_version_is_optional_for_legacy_proposals():
    jsonschema.validate(legacy_proposal, PROPOSAL_SCHEMA)
    versioned_proposal["metadata"]["continuity_contract_version"] = "1.0"
    jsonschema.validate(versioned_proposal, PROPOSAL_SCHEMA)

def test_continuity_version_rejects_unknown_value():
    proposal["metadata"]["continuity_contract_version"] = "2.0"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(proposal, PROPOSAL_SCHEMA)

def test_scene_continuity_requires_typed_anchors_and_lighting():
    jsonschema.validate(scene_with_continuity, SCENE_PLAN_SCHEMA)
    del scene_with_continuity["metadata"]["scene_continuity"]["s01"]["anchors"][0]["position"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(scene_with_continuity, SCENE_PLAN_SCHEMA)

def test_legacy_scene_plan_without_continuity_remains_valid():
    jsonschema.validate(legacy_scene_plan, SCENE_PLAN_SCHEMA)

def test_shot_continuity_requires_entity_and_change_fields():
    jsonschema.validate(shot_with_continuity, SHOT_SPEC_SCHEMA)
    del shot_with_continuity["shots"][0]["continuity"]["entities"][0]["entity_id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(shot_with_continuity, SHOT_SPEC_SCHEMA)
```
- [ ] **Step 2: Run the focused tests and confirm they fail** because the schemas do not yet define the new nested structures.

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_continuity_schemas.py -q`

Expected: failures for unknown continuity fields or missing schema validation of nested types; legacy fixtures remain valid.

- [ ] **Step 3: Add the optional version and nested contracts** to the three schemas. Keep schema artifact versions at `1.0`, keep metadata extensible, and use `additionalProperties: false` inside the new continuity records.
- [ ] **Step 4: Run the schema tests** and confirm strict structures validate while old fixtures still validate.

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_continuity_schemas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the schema contract** with its tests.

```powershell
git add docs/superpowers/specs/2026-11-22-scene-consistency-design.md docs/superpowers/plans/2026-11-22-scene-consistency.md schemas/artifacts/proposal_packet.schema.json schemas/artifacts/scene_plan.schema.json schemas/artifacts/shot_spec.schema.json tests/contracts/test_narrative_continuity_schemas.py
git commit -m "feat: define narrative continuity contracts"
```

## Task 2: Preserve Scene, Entity, and Review Identity in NarrativeAssets

**Files:**
- Modify: `lib/narrative_assets.py`
- Modify: `schemas/artifacts/asset_manifest.schema.json`
- Modify: `tests/lib/test_narrative_assets.py`
- Modify: `tests/contracts/test_narrative_workflow.py`

**Interfaces:**
- Extend `put_asset(asset_id, kind, description, path, *, state="default", metadata=None, entity_id=None)`. If `entity_id` is omitted, use `asset_id` for legacy compatibility.
- Add `register_shot(shot_id: str, scene_id: str, *, continuity_contract_version: str | None = None) -> None`. Re-registering with the same values is idempotent; conflicting scene IDs raise `ValueError`.
- Add `record_continuity_review(shot_id: str, take_id: str, review: Mapping[str, Any]) -> None`. The catalog fills `reviewed_path` from the current take and validates project-relative evidence paths.
- Review dimensions are `identity_wardrobe`, `location_anchors`, `camera_continuity`, `light_and_look`, and `story_state`; values are `pass`, `intentional_change`, `drift`, or `unclear`.
- Export each review as `take_id`, `reviewed_path`, `dimensions` (all five keys required), `notes` (keyed by dimension), `evidence_paths` (at least one project-relative path), and optional `override_reason`; any `drift` or `unclear` dimension requires a non-empty override reason.
- `asset_manifest()` exports `metadata.continuity_shots` keyed by shot ID (`scene_id`, optional contract version) and `metadata.continuity_reviews` keyed by shot ID for current-path reviews only.
- `apply_enhancement()` invalidates review evidence when it changes the selected take path.

- [ ] **Step 1: Write catalog tests** with these names and assertions:

```python
def test_scene_id_survives_multiple_shots_in_manifest(tmp_path):
    assert {asset["scene_id"] for asset in manifest["assets"]} == {"s01"}

def test_legacy_catalog_scene_id_defaults_to_shot_id(tmp_path):
    assert manifest["assets"][0]["scene_id"] == "shot-legacy"

def test_state_variants_share_entity_id_and_review_requires_all_dimensions(tmp_path):
    assert catalog.data["assets"]["hero-wet"]["entity_id"] == "hero"
    with pytest.raises(ValueError, match="story_state"):
        catalog.record_continuity_review("s01-sh01", "take-a", incomplete_review)

def test_review_drift_requires_override_reason(tmp_path):
    with pytest.raises(ValueError, match="override"):
        catalog.record_continuity_review("s01-sh01", "take-a", drift_review)
    catalog.record_continuity_review("s01-sh01", "take-a", {**drift_review, "override_reason": "approved exception"})

def test_review_rejects_unknown_dimension_keys(tmp_path):
    invalid_review["dimensions"]["costume"] = "pass"
    with pytest.raises(ValueError, match="unsupported dimension"):
        catalog.record_continuity_review("s01-sh01", "take-a", invalid_review)

def test_review_rejects_blank_override_reason(tmp_path):
    invalid_review["override_reason"] = "  "
    with pytest.raises(ValueError, match="override"):
        catalog.record_continuity_review("s01-sh01", "take-a", invalid_review)

def test_enhancement_invalidates_review_of_previous_path(tmp_path):
    assert "s01-sh01" not in catalog.asset_manifest()["metadata"]["continuity_reviews"]
```
- [ ] **Step 2: Run the focused tests and confirm they fail** on missing APIs and scene/review export behavior.

Run: `.\.venv\Scripts\python.exe -m pytest tests/lib/test_narrative_assets.py tests/contracts/test_narrative_workflow.py -q`

Expected: new behavior tests fail; existing catalog tests continue to pass.

- [ ] **Step 3: Implement shot registration, entity IDs, and review persistence** without changing existing positional call sites. Resolve missing legacy scene IDs as `shot_id` when loading/exporting.
- [ ] **Step 4: Export continuity metadata and invalidate stale reviews** when enhancement changes the current selected media path; extend the asset-manifest metadata schema.
- [ ] **Step 5: Re-run the focused tests** and confirm strict behavior and legacy behavior both pass.

Run: `.\.venv\Scripts\python.exe -m pytest tests/lib/test_narrative_assets.py tests/contracts/test_narrative_workflow.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the catalog and schema changes.**

```powershell
git add lib/narrative_assets.py schemas/artifacts/asset_manifest.schema.json tests/lib/test_narrative_assets.py tests/contracts/test_narrative_workflow.py
git commit -m "feat: persist narrative continuity metadata"
```

## Task 3: Add Continuity Validation and Shot Context Assembly

**Files:**
- Create: `lib/narrative_continuity.py`
- Create: `tests/lib/test_narrative_continuity.py`

**Interfaces:**
- `ContinuityValidationError(ValueError)` exposes an ordered `issues: tuple[str, ...]` suitable for a stage report.
- `continuity_mode(proposal_packet: Mapping[str, Any]) -> Literal["legacy", "strict"]` returns `legacy` when the marker is absent and `strict` for version `"1.0"`; unknown versions raise `ContinuityValidationError`.
- `validate_scene_plan_continuity(scene_plan: Mapping[str, Any], *, strict: bool) -> None` checks required scene maps and stable location IDs in strict mode; it is a no-op for legacy mode.
- `validate_shot_continuity(scene_plan: Mapping[str, Any], shot_specs: Mapping[str, Any], catalog_data: Mapping[str, Any], project_root: str | Path, *, strict: bool) -> None` checks shot/scene IDs, locations, asset identity/state, paths, and entity state transitions.
- `build_shot_context(shot: Mapping[str, Any], scene_contract: Mapping[str, Any], catalog_data: Mapping[str, Any], project_root: str | Path) -> dict[str, Any]` returns stable descriptors, role-labeled reference paths, location locks, carried states, intentional changes, and shot-specific action/framing. It does not write provider syntax or select a provider.
- For each strict shot, validation requires a `references[]` entry with role `location` whose catalog asset is kind `location`, has `entity_id == scene_contract["location_id"]`, and state `master_plate`; this binds the approved empty plate at the asset-sheets gate.

- [ ] **Step 1: Write validator/context tests** with these names and assertions:

```python
def test_strict_scene_requires_location_contract():
    with pytest.raises(ContinuityValidationError, match="s01"):
        validate_scene_plan_continuity(scene_plan_without_location, strict=True)

def test_legacy_mode_skips_new_continuity_requirements():
    validate_shot_continuity(legacy_scene_plan, legacy_shot_specs, legacy_catalog, project_root, strict=False)

def test_nonadjacent_entity_state_change_requires_declared_delta():
    with pytest.raises(ContinuityValidationError, match="hero.*state"):
        validate_shot_continuity(scene_plan, recurring_hero_shots, catalog_data, project_root, strict=True)

def test_shot_with_unknown_scene_or_asset_fails_before_generation():
    with pytest.raises(ContinuityValidationError, match="scene_id|asset_id"):
        validate_shot_continuity(scene_plan, shot_with_unknown_scene_or_asset, catalog_data, project_root, strict=True)

def test_reference_missing_mismatched_or_outside_project_fails_before_generation():
    with pytest.raises(ContinuityValidationError, match="reference path"):
        validate_shot_continuity(scene_plan, shot_with_invalid_reference_path, catalog_data, project_root, strict=True)
    mismatched = copy.deepcopy(shot_specs)
    mismatched["shots"][0]["references"][1]["path"] = catalog_data["assets"]["loc-s01-master"]["path"]
    with pytest.raises(ContinuityValidationError, match="reference path"):
        validate_shot_continuity(scene_plan, mismatched, catalog_data, project_root, strict=True)

def test_missing_approved_location_plate_reference_fails():
    with pytest.raises(ContinuityValidationError, match="master plate"):
        validate_shot_continuity(scene_plan, shot_without_location_reference, catalog_data, project_root, strict=True)

def test_intentional_nonadjacent_state_change_passes():
    validate_shot_continuity(scene_plan, shots_with_declared_change, catalog_data, project_root, strict=True)

def test_context_copies_descriptor_and_role_labeled_references():
    assert context["stable_descriptors"][0] == approved_descriptor
    assert {ref["role"] for ref in context["references"]} == {"identity", "location"}
```
- [ ] **Step 2: Run the focused tests and confirm they fail** because the module and interfaces do not exist.

Run: `.\.venv\Scripts\python.exe -m pytest tests/lib/test_narrative_continuity.py -q`

Expected: import failures for the new module.

- [ ] **Step 3: Implement mode resolution and scene-plan validation** with shot-specific issue messages.
- [ ] **Step 4: Implement ordered shot validation**. Track the last state per `entity_id` across absent shots and scenes; require a matching `intentional_changes` entry when state changes. Reset location locks only when the shot enters a new `scene_id`.
- [ ] **Step 5: Implement model-neutral shot context assembly** from the approved catalog records, copying stable descriptors exactly and including only references linked to that shot.
- [ ] **Step 6: Run the focused tests** and confirm state carry, exception reporting, and prompt-context values.

Run: `.\.venv\Scripts\python.exe -m pytest tests/lib/test_narrative_continuity.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the validator and tests.**

```powershell
git add lib/narrative_continuity.py tests/lib/test_narrative_continuity.py
git commit -m "feat: validate narrative continuity inputs"
```

## Task 4: Wire the Contract into Cinematic Planning and Assets Stages

**Files:**
- Modify: `skills/pipelines/cinematic/proposal-director.md`
- Modify: `skills/pipelines/cinematic/scene-director.md`
- Modify: `skills/pipelines/cinematic/asset-director.md`
- Modify: `skills/creative/narrative-consistency.md`
- Modify: `docs/narrative-production.md`
- Modify: `pipeline_defs/cinematic.yaml`
- Modify: `tests/contracts/test_narrative_cinematic.py`
- Modify: `tests/contracts/test_narrative_norms.py`

**Interfaces:**
- New narrative-generated proposals record `metadata.continuity_contract_version: "1.0"`; existing projects stay legacy unless the user opts in at an approved proposal checkpoint and the choice is logged as `approval_policy` / `Scene continuity contract version`.
- The scene director creates `metadata.scene_continuity` and calls `validate_scene_plan_continuity` before reference-sheet or empty-plate generation.
- After the asset-sheets approval and shot-spec authoring, the asset director calls `validate_shot_continuity` before prompt compilation or video-shot generation.
- The asset director passes `build_shot_context` into its provider-specific Layer 3 prompt workflow, then uses `record_continuity_review` for candidate takes and re-records review after enhancement.

- [ ] **Step 1: Add failing contract tests** with these names and assertions:

```python
def test_scene_director_runs_planning_check_before_reference_generation():
    assert text.index("validate_scene_plan_continuity") < text.index("generate the location plate")

def test_asset_director_runs_shot_check_after_asset_sheets_gate():
    pipeline = text[text.index("## Narrative Asset Pipeline"):]
    assert pipeline.index("asset_sheets approval") < pipeline.index("validate_shot_continuity") < pipeline.index("Batch takes")

def test_proposal_director_versions_new_mode_and_logs_existing_project_opt_in():
    assert "continuity_contract_version" in text
    assert "Scene continuity contract version" in text
    assert "approval_policy" in text
```
- [ ] **Step 2: Run the focused contract tests and confirm they fail** on missing instructions and stage ordering.

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_cinematic.py tests/contracts/test_narrative_norms.py -q`

Expected: failures for missing continuity workflow language; unaffected existing approval assertions remain green.

- [ ] **Step 3: Update proposal and scene directors** with version selection, opt-in logging, structured scene contracts, and the pre-asset planning check.
- [ ] **Step 4: Update the asset director and narrative consistency skill** with post-asset-sheet validation, model-neutral context use, per-shot review statuses, salient-state reference policy, and enhancement re-review.
- [ ] **Step 5: Update the pipeline manifest review focus and narrative-production guide** without changing the existing approval stages or source-led behavior.
- [ ] **Step 6: Run the focused contract tests** and confirm the documented order and legacy branch are explicit.

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_cinematic.py tests/contracts/test_narrative_norms.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the workflow and documentation updates.**

```powershell
git add skills/pipelines/cinematic/proposal-director.md skills/pipelines/cinematic/scene-director.md skills/pipelines/cinematic/asset-director.md skills/creative/narrative-consistency.md docs/narrative-production.md pipeline_defs/cinematic.yaml tests/contracts/test_narrative_cinematic.py tests/contracts/test_narrative_norms.py
git commit -m "docs: wire continuity checks into cinematic workflow"
```

## Task 5: Enforce Current Review Evidence Before Compose

**Files:**
- Modify: `tools/video/video_compose.py`
- Modify: `tests/contracts/test_narrative_edit_integration.py`
- Create: `tests/contracts/test_narrative_continuity_workflow.py`
- Modify: `tests/lib/test_narrative_enhancement.py`

**Interfaces:**
- Extend `_validate_narrative_selection(inputs)` to read the approved proposal marker and require continuity reviews only for shot records carrying contract version `"1.0"`.
- For strict shots, the asset manifest, asset checkpoint, catalog, and edit checkpoint must agree on selected `take_id`, `scene_id`, and current media path.
- Reject missing/stale review evidence and any unresolved `drift`/`unclear` dimension. Accept an explicit `override_reason` and legacy shots without continuity markers.
- Preserve all existing selected-take and checkpoint checks.

- [ ] **Step 1: Write integration tests** with these names and assertions:

```python
def test_compose_rejects_strict_selection_without_current_review(tmp_path):
    assert not result.success
    assert "continuity review" in result.error.lower()

def test_compose_rejects_review_for_pre_enhancement_path(tmp_path):
    assert not result.success
    assert "stale" in result.error.lower()

def test_compose_allows_legacy_selection_without_continuity_review(tmp_path):
    assert result.success

def test_compose_allows_drift_only_with_recorded_override(tmp_path):
    assert result.success

def test_strict_narrative_pilot_preserves_state_and_review_through_compose(tmp_path):
    assert [item["scene_id"] for item in manifest["assets"] if item["type"] == "video"] == ["s01", "s01", "s02"]
    assert result.success
```
- [ ] **Step 2: Run the focused integration tests and confirm strict cases fail** because the compose guard does not yet inspect continuity evidence.

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_edit_integration.py tests/lib/test_narrative_enhancement.py -q`

Expected: new strict-mode cases fail; existing legacy narrative selection cases pass.

- [ ] **Step 3: Extend `_validate_narrative_selection`** to check strict-shot review records against the selected catalog take and approved manifest/checkpoints.
- [ ] **Step 4: Confirm the compose guard rejects a manifest whose review path no longer matches the enhanced selected media**, while a renewed assets approval with fresh evidence passes.
- [ ] **Step 5: Run the focused integration tests** and confirm stale paths are rejected while legacy and documented-override cases behave as specified.

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_edit_integration.py tests/contracts/test_narrative_continuity_workflow.py tests/lib/test_narrative_enhancement.py -q`

Expected: PASS.

- [ ] **Step 6: Run the full relevant contract set** for schemas, catalog, validation, workflow instructions, and compose selection.

Run: `.\.venv\Scripts\python.exe -m pytest tests/contracts/test_narrative_continuity_schemas.py tests/contracts/test_narrative_cinematic.py tests/contracts/test_narrative_norms.py tests/contracts/test_narrative_edit_integration.py tests/contracts/test_narrative_continuity_workflow.py tests/contracts/test_narrative_workflow.py tests/lib/test_narrative_assets.py tests/lib/test_narrative_continuity.py tests/lib/test_narrative_enhancement.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the compose guard and integration tests.**

```powershell
git add tools/video/video_compose.py tests/contracts/test_narrative_edit_integration.py tests/contracts/test_narrative_continuity_workflow.py tests/lib/test_narrative_enhancement.py
git commit -m "feat: require current continuity review before compose"
```

## Self-Review

- **Spec coverage:** Scene/shot contracts, versioned legacy behavior, asset identity and states, cross-scene carry-forward, reference-aware prompt context, take review, enhancement invalidation, and compose enforcement each map to Tasks 1–5.
- **Step scan:** Every task defines a test command, implementation boundary, and expected result; no task requires a provider call or changes the selected production route.
- **Type consistency:** Scene IDs, shot IDs, entity IDs, contract version, and review metadata have the same names across schemas, catalog, validator, skills, and compose guard.
- **Review Focus:** All five input classes map to named tests in their owning tasks.
- **Proportion:** The plan covers one cross-stage feature whose boundaries share the same continuity contract; keeping it as one ordered plan avoids shipping incompatible artifact, catalog, and compose semantics.

## Execution Note

The plan is not implementation authorization. At execution time, use an isolated worktree if the selected execution skill requires one, and preserve any unrelated working-tree changes.

