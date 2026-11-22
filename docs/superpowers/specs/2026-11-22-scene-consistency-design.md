# Scene Consistency Design

**Status:** Proposed for review  
**Scope:** Cinematic pipeline, `narrative_generated` productions  
**Decision:** Strengthen the existing workflow with structured continuity data, pre-generation checks, reference-aware prompt context, and a review record. Do not add a provider or make 3D the default.

## Proposed policy defaults for review

These are implementation defaults proposed by the agent; the user can change them when reviewing this document.

- Make a separate approved reference for a visually salient state that persists across shots (for example, wet wardrobe, visible damage, or a changed prop). Describe a transient one-shot state in the shot contract without creating a permanent asset variant.
- Mark projects with a continuity-contract version. New projects use strict validation; existing projects remain in legacy mode unless the user opts in. Opt-in applies to newly planned/generated shots and does not silently invalidate already approved shots.
- A `drift` take is ineligible by default; the user may explicitly override it with a recorded reason. An `unclear` result must be resolved or explicitly overridden before the take can be selected.
- Continuity review evidence must match the final selected media path. If enhancement changes that path, refresh the evidence and review before renewing assets approval.

## Intent

Make recurring characters, locations, props, and their changing states more consistent across generated shots. The project already has asset-first guidance, shot specifications, a narrative asset catalog, and human approval gates. This design makes those contracts easier to validate and carries them from scene planning through prompt preparation and take selection.

The system must preserve story-motivated changes. It should flag unexplained drift, not demand pixel-identical frames across different cameras or times.

## Goals

- Give each shot an unambiguous scene, location, entity-state, and predecessor relationship.
- Validate continuity inputs before any generation call.
- Build shot context from the approved descriptor and only the references relevant to that shot.
- Preserve scene identity separately from shot identity in the asset catalog and exported manifest.
- Give the assets reviewer a concise, evidence-based continuity review for candidate takes.
- Keep existing human selection and approval gates authoritative.

## Non-goals

- Changing video providers, model families, render runtime, or generation quality tier.
- Making a 3D scene mandatory for narrative productions.
- Automatically selecting a take or replacing human approval with a model score.
- Enforcing exact pixel similarity between shots with different framing, lighting time, or intended story state.
- Extending this first change to source-led, explainer, or other pipelines.

## Constraints

- OpenMontage remains instruction-driven; Python helpers validate and persist data but do not make creative decisions.
- Generation remains behind the existing proposal, model-route, assets, and take-selection gates.
- `scene_plan` and `shot_spec` remain the creative contracts; provider-specific prompt syntax stays in the provider skill/compiler layer.
- Existing project artifacts must remain readable. Strict validation is versioned and enabled by default only for new projects; existing projects stay in legacy mode unless the user opts in.
- A continuity record distinguishes stable facts from intentional changes, including wardrobe, weather, damage, prop ownership, lighting changes, camera-axis reversals, and time jumps.

## Approaches considered

### 1. Documentation-only checklist

Clarify the current director instructions and keep every check manual. This is the smallest change, but it cannot reliably catch missing references, scene/shot ID confusion, or a state conflict before generation.

### 2. Strengthen the existing workflow — selected

Add typed scene and shot continuity fields, a pre-generation validator, model-neutral prompt context assembly, and a human-reviewed take continuity record. Reuse `NarrativeAssets`, existing provider-specific guidance, `frame_sampler`, and the existing assets gate. This closes the handoff gaps without changing the production route.

### 3. 3D-first scene continuity

Represent persistent locations as editable 3D scenes and render shots from the shared geometry. This is appropriate for projects where reverse angles and camera travel must preserve exact spatial layout, but it is expensive and does not solve character identity or prop-state continuity by itself. Keep it as an opt-in route for geometry-sensitive projects.

The selected approach follows the user's choice on 2026-11-22. The 3D route remains available for a later, project-specific decision.

## Proposed design

### 1. Scene-level continuity contract

Extend `scene_plan.metadata` with a typed, per-scene continuity record while retaining the current human-readable `location_map` during migration. The record should identify:

- `scene_id` and stable `location_id`;
- approved empty-plate reference;
- master camera angle and camera axis;
- named anchors with camera-relative positions;
- base key-light direction and shadow direction;
- scene-level constants such as time, weather, and palette;
- explicitly allowed scene changes.

The free-text `location_map` becomes a readable summary of this record, not a separate source of truth. Run a structural check before generating reference sheets or empty plates; it can validate descriptors, scene IDs, and planned anchors without requiring generated files. Bind the approved empty plate to its location record at the existing `asset_sheets` review. Run the strict shot-input check after that review and before video-shot generation. If the plate or spatial contract changes, return to the appropriate scene-plan or asset approval gate before generating affected shots.

### 2. Shot-level continuity contract

Extend each `shot_spec` with a structured continuity section containing:

- `previous_shot_id` when the shot continues an earlier beat;
- referenced entity IDs and their expected states;
- state facts carried from the previous shot;
- intentional changes, with a reason such as a time jump or camera-axis reversal;
- the location ID and spatial/lighting locks inherited from the scene;
- screen direction, gaze targets, and relevant hand/prop states.

Keep the existing `scene_id`, `shot_id`, `references`, and prose fields. The new fields should make facts addressable without removing the descriptive language the prompt compiler needs.

Track entity state across its last appearance, including nonadjacent shots and scene boundaries. Location geometry and lighting are scene-scoped and reset to the next scene's contract; character, wardrobe, and prop states carry forward unless the continuity record declares a reset, time jump, or other change. A first appearance starts from its approved canonical state.

### 3. Narrative asset catalog and IDs

Store `scene_id` on each shot record in `NarrativeAssets`; continue to key takes and asset links by `shot_id`. Export the real `scene_id` in `asset_manifest` instead of copying `shot_id` into it. For old catalog entries without a scene ID, interpret `scene_id = shot_id` until the project is migrated.

Assets remain versioned by state (for example, `hero-dry` and `hero-wet`). Each shot links only the approved asset states it needs. The catalog records data and selection; it does not infer the correct state or approve references.

Under the proposed default, only visually salient states that persist across shots require separate approved references. Transient states can remain textual shot-level facts. The scene/shot record must still state which current state is expected.

### 4. Pre-generation validation and prompt context

Add two narrative continuity validation steps: a planning check before reference-sheet/plate generation, and a strict shot-input check after the asset-sheets gate and before video-shot generation. The latter should fail with a shot-specific explanation when:

- a shot references a missing scene, location, entity, asset, or predecessor;
- a recurring entity is missing an approved canonical reference or expected state;
- shots in one scene disagree on the locked location map without an explicit change;
- a prior shot's ending state conflicts with the next shot's opening state and no intentional change is declared;
- a required reference path is unavailable.

Build a model-neutral prompt context from the validated shot spec and catalog: stable descriptors copied verbatim, role-labeled references (identity, location, prop, style), inherited scene locks, current state, intentional changes, then shot-specific action and framing. The selected provider's Layer 3 skill remains responsible for translating that context into the provider's prompt dialect and binding its reference inputs. The compiler must not silently choose another provider or model.

### 5. Candidate-take continuity review

At the existing assets gate, prepare representative frames for each candidate take and record a review with these dimensions:

| Dimension | Review question |
|---|---|
| Identity and wardrobe | Is the approved character still recognizable, with the expected costume and marks? |
| Location and anchors | Are the location and named landmarks spatially plausible for this camera? |
| Camera continuity | Are axis, screen direction, body orientation, and gaze consistent or intentionally changed? |
| Light and look | Do light direction, palette, and visual treatment follow the scene contract or a declared change? |
| Story state | Do props, hands, damage, weather, and action state carry forward or change for a stated reason? |

Each dimension records `pass`, `intentional_change`, `drift`, or `unclear`, with a short note and frame evidence. A `drift` or `unclear` result returns to asset/shot design for review. Human selection remains required. Do not make a vision-model score a blocking criterion in this first version; it can be evaluated later against human-reviewed examples.

The proposed selection rule excludes `drift` by default; an explicit user override with a reason is allowed. `unclear` must be resolved or explicitly overridden. Re-run this review against the current selected media after any enhancement that changes the file, then renew the existing assets approval.

## Rollout

1. Finalize field names and backward-compatibility behavior for the continuity records, including a project-level `continuity_contract_version` marker.
2. Extend the artifact schemas and catalog export while preserving old-project reads.
3. Add the pre-generation validator and model-neutral prompt-context assembly; connect them to the cinematic asset director path.
4. Add the take-review record and contact-sheet evidence to the assets checkpoint.
5. Pilot one scene with one recurring character, one location, 2–3 shots, and one declared state or camera-axis change.
6. Review the pilot with the user, then enable the contract for new narrative-generated projects.

## Acceptance criteria

- A narrative-generated shot cannot reach video-shot generation without a valid location contract and required approved assets; reference sheets and empty plates can be generated after the planning check and before their approval gate.
- A shot's prompt context contains the exact approved stable descriptor and the correct role-labeled references.
- Missing IDs, missing paths, or unexplained carry-forward conflicts are reported before a provider call.
- Multiple shots in one scene retain the same `scene_id` in the catalog and manifest while keeping unique `shot_id` values.
- Candidate-take review distinguishes intentional story changes from unexplained visual drift and includes frame evidence.
- Existing human approval and provider/model decision gates remain in force.

## Risks and mitigations

- **Over-constraining creative changes:** represent changes explicitly and allow camera, time, weather, wardrobe, and state transitions when justified.
- **Schema changes break old runs:** keep new fields optional for existing artifacts, version the contract, scope strict validation to new or opted-in projects, and provide a legacy `scene_id = shot_id` interpretation.
- **Reference overload confuses generation:** include only shot-relevant references, each with an explicit role.
- **Automated visual scoring is unreliable:** keep the first review human-led and use any model score as advisory until calibrated. Tie review evidence to the current media path so enhancement cannot leave a stale review.
- **Character-sheet guidance differs:** reconcile the project rule that omits the head from the front full-body panel with the general LIRA template that includes a head-to-toe front view. Document which image anchors identity and which anchors wardrobe/body.

## Builder-owned details

The implementer may choose the exact property names and helper boundaries, provided the data remains model-neutral, the old catalog fallback is preserved, and the acceptance criteria above hold. The implementer should also choose whether to extend `shot_prompt_builder.py` or introduce a narrative-specific context builder; the design does not require that generic helper to become the provider prompt compiler.

No code changes are authorized by this design document. Implementation begins only after the user approves this design.
