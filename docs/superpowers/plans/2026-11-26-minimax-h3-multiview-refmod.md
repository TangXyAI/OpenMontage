# MiniMax H3 Multi-View Character RefMod Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax.

**Goal:** Generate five separate character reference images and preserve them as five independent picture members in one local MiniMax H3 RefMod bundle.

**Architecture:** `NarrativeAssets` stores the ordered role/path set and hashes each source. `comfyui_refmod` sends the five approved files to the RefMod extractor in one API workflow with `image_refs="separate"`, verifies a complete bundle, then records its provenance. Shot-level prompt labels are assigned across all active bundle members; existing single-image RefMods remain compatible.

**Tech Stack:** Python, ComfyUI API workflows, JSON Schema, Markdown.

**Spec:** `docs/superpowers/specs/2026-11-26-minimax-h3-multiview-refmod-design.md`

**Execution:** Native, in the current branch, without a worktree, as requested.

## Global Constraints

- New character sets contain exactly five distinct files in this order: shoulder-up front portrait; shoulder-up side portrait; front full-body without head; side full-body without head; back full-body with head.
- The five images are separate files and separate RefMod bundle members; no contact sheet or collage.
- Extract one RefMod per approved character/state and load it through one Loader slot.
- Existing single-image assets, already approved three-image character sets, and existing single-source RefMods remain unchanged unless explicitly regenerated. Legacy three-image records with a top-level `reference_images` list continue to use their canonical `path` for RefMod extraction.
- Record all five source paths and content hashes in order. Any missing, changed, or reordered source makes the bundle stale.
- Require the live extraction node's `refs_image` IMAGE autogrow prefix and capacity of at least five, `image_refs` option `separate`, `budget_policy` option `error`, and `extraction_preset` option `identity_encode`. New five-view characters use Full Reference at 1024px with `max_tokens=0`.
- Assign `<Picture N>` from the actual ordered reference map across active bundles. Do not apply the hosted API's nine-image cap as a local RefMod cap without evidence from the selected local graph.
- Preserve the existing maximum of eight RefMod Loader slots.
- No new tests are added and no tests are run in this task. Update the existing three-image validator test to the new five-file contract.

## Review Focus

- Missing, duplicate, reordered, or out-of-project character image: reject before extraction.
- Legacy single-image or approved three-image character record: continue through the legacy path without migration.
- Any source changed during staging, upload, or extraction: discard the new output and mark/reject the old bundle as stale.
- Selected ComfyUI node missing any required socket, or its visual budget unable to preserve all five images: block before recording a RefMod.
- Multiple character/location/prop bundles: keep global picture labels aligned with the extractor's ordered reference map, and do not misapply the hosted API limit to the local path.
- Existing Loader component filters or zero visual strengths: reset visual slots so an earlier graph setting cannot remove a project reference after label assignment.
- Direct `comfyui_video` inputs: reject `prompt_labels` whose count does not equal the proven source-reference member count.

## Files and Responsibilities

| File | Responsibility |
|---|---|
| `lib/narrative_assets.py` | Validate and persist ordered character views, source-set provenance, staleness, and dynamic picture labels. |
| `schemas/artifacts/asset_manifest.schema.json` | Allow ordered source-reference records and multiple picture labels while preserving legacy records. |
| `tools/video/comfyui_refmod.py` | Accept legacy one-image input or the approved five-image set, bind/hash all sources, and register one complete bundle. |
| `tools/_comfyui/h3_contracts.py` | Keep the legacy extraction contract and define a multi-image-only autogrow check. |
| `tools/_comfyui/workflows/refmod_extract_api.json` | Provide five `LoadImage` nodes connected to the extractor's ordered image sockets. |
| `tools/_comfyui/refmod_workflow.py` | Validate the complete prompt-label range for each RefMod. |
| `tools/video/comfyui_video.py` | Accept and preserve multiple picture labels in local H3 RefMod provenance. |
| `tests/lib/test_narrative_assets.py` | Update the existing character-reference validator test from three to five distinct files. |
| `skills/pipelines/cinematic/asset-director.md` | Direct the cinematic asset stage to create, approve, record, and extract five separate views. |
| `skills/creative/narrative-consistency.md` | Define the five-view order and no-collage rule. |
| `.agents/skills/minimax-h3/SKILL.md` | Explain one multi-image RefMod bundle, its separate members, and dynamic labels. |
| `docs/superpowers/specs/2026-11-26-minimax-h3-multiview-refmod-design.md` | Mark the approved design status. |

---

### Task 1: Store the Five-View Set and Its Provenance

**Files:**
- Modify: `lib/narrative_assets.py`
- Modify: `schemas/artifacts/asset_manifest.schema.json`
- Modify: `tests/lib/test_narrative_assets.py` (update the existing three-image contract only)

**Interfaces:**
- Define `CHARACTER_REFERENCE_ROLES` in `lib/narrative_assets.py` with the ordered values `portrait_front`, `portrait_side`, `full_body_front_headless`, `full_body_side_headless`, `full_body_back_headed`.
- Define `character_reference_mode(asset)` so a valid five-role record requires full source provenance; a legacy three-entry `reference_images` list stays on the canonical-path single-image path.
- Keep `validate_character_sheet(descriptor, sheet_paths)` but require five unique existing paths.
- Extend `NarrativeAssets.put_asset(..., reference_images: Sequence[Mapping[str, str]] | None = None)`. When supplied for a new character, require the five roles in the declared order, five unique project-relative paths, existing files, and the first path equal to the asset's canonical `path`. When omitted, preserve current legacy behavior.
- Extend `NarrativeAssets.register_refmod_asset(..., source_references: Sequence[Mapping[str, str]] | None = None)`. Each multi-image record contains `role`, `path`, and `source_sha256`; retain `source_path` as the first path and `source_sha256` as the ordered source-set digest. Omission preserves the single-source record shape.
- Update `_refmod_is_current` to compare the current ordered role/path set and every file hash when `source_references` exists; do not consider a five-view asset current when its RefMod record omits the full source set. Retain the current single-path check for legacy records.
- Add optional `source_references` to the asset-manifest RefMod record schema; do not make it required for old manifests.

- [x] Update `validate_character_sheet` to require exactly five distinct existing files and keep descriptor validation.
- [x] Add optional ordered `reference_images` storage to `NarrativeAssets.put_asset`; validate roles, project containment, uniqueness, file existence, and the primary-path match.
- [x] Add optional ordered `source_references` to RefMod registration and compute/check the stable digest over ordered role, path, and content-hash records.
- [x] Preserve the legacy freshness branch for single-image and three-image records; require complete `source_references` for five-view assets in both registration and freshness checks.
- [x] Update the existing validator test's file list and expected count from three to five; do not add a new test case.
- [x] Add the optional source-reference schema object with closed properties `role`, `path`, and `source_sha256`.

### Task 2: Extract Five Images into One RefMod Bundle

**Files:**
- Modify: `tools/video/comfyui_refmod.py`
- Modify: `tools/_comfyui/h3_contracts.py`
- Modify: `tools/_comfyui/workflows/refmod_extract_api.json`

**Interfaces:**
- Preserve `reference_path: str` for a legacy single-image asset.
- Add `reference_images: list[dict[str, str]]` with entries `{role, path}` for the new character set. Require exactly one of `reference_path` or `reference_images`; for a new five-view character, verify the list exactly matches the approved catalog record.
- Include `reference_images` in the idempotency input and use the ordered source-set digest when deriving the output path and cache identity.
- Keep workflow node `1` for `portrait_front`; add `LoadImage` nodes `5`, `6`, `7`, and `8` for the other views. Connect node `1` to `refs_image.ref_image_0`, then nodes `5`–`8` to `refs_image.ref_image_1`–`refs_image.ref_image_4`, in role order.

- [x] Update the tool input schema and runtime validation to accept either one legacy path or the exact five approved role/path entries, never both.
- [x] Add the four `LoadImage` nodes and their ordered RefMod extractor connections; keep `image_refs` set to `separate`.
- [x] Inspect the live node schema and require a `refs_image` IMAGE autogrow template with prefix `ref_image_` and max at least five. Verify live `image_refs` contains `separate`, `budget_policy` contains `error`, and `extraction_preset` contains `identity_encode`; keep the legacy single-image input check unchanged.
- [x] For new five-view characters, set `mode=Full Reference`, `extraction_preset=identity_encode`, `ref_resolution=1024`, `identity=0`, `max_tokens=0`, `merge=false`, `motion_only=false`, `multiplier=1`, `image_refs=separate`, and `budget_policy=error`. Keep the existing single-image workflow settings unchanged.
- [x] Upload and snapshot all five files, verify each staged snapshot hash before and after upload, then recheck every original source hash immediately before submission and after extraction.
- [x] Verify the saved RefMod metadata contains exactly five image members with the expected ordered `separate ref i/5` member tags before copying or registering it. On mismatch, remove the unregistered output and return an error.
- [x] Register the ordered source references and aggregate source-set digest. Keep the existing one-image path, cache behavior, and output shape working.

### Task 3: Map Bundle Members to H3 Picture Labels

**Files:**
- Modify: `lib/narrative_assets.py`
- Modify: `tools/_comfyui/refmod_workflow.py`
- Modify: `tools/video/comfyui_video.py`
- Modify: `schemas/artifacts/asset_manifest.schema.json`

**Interfaces:**
- `NarrativeAssets.refmods_for_shot(...)` continues to return one row per asset/Loader slot and adds `prompt_labels: list[str]`; preserve `prompt_label` as the first label for compatibility.
- Assign labels over the deterministic ordered members of the complete active RefMod set. A legacy single-image RefMod receives one label; a five-image character bundle receives five consecutive labels.
- `_validate_refs` accepts `prompt_labels` and legacy `prompt_label`; it verifies continuity, global order, and that the prompt contains every label in order.
- `comfyui_video` carries all labels in workflow provenance; the manifest accepts optional `prompt_labels` alongside legacy `prompt_label`.

- [x] Update `refmods_for_shot` to count members from `source_references` and assign a consecutive label range across all linked assets.
- [x] Update RefMod workflow validation to normalize a legacy singular label to a one-item list; for multi-image records require source references and picture labels to have the same count, match the five ordered roles, and validate every label in global order.
- [x] Update `comfyui_video` input handling and `_refmod_provenance` to preserve `prompt_labels`, ordered source roles, and source hashes.
- [x] Extend both asset-manifest RefMod schema locations with optional `prompt_labels` / source-reference fields while keeping legacy fields valid.
- [x] Keep the existing eight-Loader-slot guard and reset any existing `components_N` / `visual_strength_N` fields so project image members remain visible. Do not add a hard nine-image guard to local RefMod solely from the hosted API contract.

### Task 4: Update the Cinematic Instructions

**Files:**
- Modify: `skills/pipelines/cinematic/asset-director.md`
- Modify: `skills/creative/narrative-consistency.md`
- Modify: `.agents/skills/minimax-h3/SKILL.md`

- [x] Replace the three-panel instruction with five separate files in the exact approved order; explicitly reject a contact sheet or collage.
- [x] Instruct the asset stage to keep one descriptor/state across the views, save each role as a separate project path, and register the ordered `reference_images` set.
- [x] Route new characters to one RefMod extraction with `image_refs="separate"`; require all five sources and halt on incomplete node support or budget errors.
- [x] Describe picture labels as dynamic across active bundle members, not fixed globally to `<Picture 1>` through `<Picture 5>`.
- [x] State that existing approved three-image character sets retain legacy behavior until regenerated; locations, props, and single-image RefMods stay unchanged.

### Task 5: Review the Completed Changes

**Files:** All files in Tasks 1–4.

- [x] Mark the approved design document's status `Approved by user on 2026-11-27`.
- [x] Read the final diff and verify no active cinematic/H3 instruction still requests a three-panel character collage.
- [x] Parse `tools/_comfyui/workflows/refmod_extract_api.json` and `schemas/artifacts/asset_manifest.schema.json` as JSON.
- [x] Run `git diff --check` and inspect the final status to confirm only intended files changed.
- [x] Do not run the test suite or add new tests; the only test-file change is updating the existing validator contract.

## Self-Review

- **Spec coverage:** Five standalone role-ordered images, one multi-image bundle, full source provenance/staleness, local node and budget blockers, dynamic global labels, and legacy compatibility map to Tasks 1–5.
- **Step scan:** Every task names its files, interfaces, and one implementation boundary; no provider, hosted API, or non-character asset behavior is changed.
- **Type consistency:** `reference_images` entries use `role`/`path`; `source_references` entries use `role`/`path`/`source_sha256`; shot-level `prompt_labels` is always an ordered string list.
- **Review focus:** Path completeness, source drift, node/budget compatibility, labels across bundles, and legacy behavior are addressed directly by the owning tasks and final review.
- **Proportion:** The plan follows the approved design's five implementation responsibilities without changing video generation routing or the broader pipeline.
