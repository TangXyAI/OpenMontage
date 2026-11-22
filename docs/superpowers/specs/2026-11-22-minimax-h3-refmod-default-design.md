# MiniMax H3 RefMod Defaults

**Status:** Approved by user on 2026-11-22

**Scope:** Local ComfyUI MiniMax H3 asset generation in the cinematic pipeline
**Decision:** Make project-scoped RefMod extraction and application the default for reusable approved assets.

## Intent

When an approved cinematic asset set contains reusable characters, clothing states, locations, or important props, prepare MiniMax H3 RefMods from those approved references and apply the relevant Mods during local H3 Ref2VA shot generation. Keep exact first/last-frame shots on the native FL2VA path, and keep one-off motion/video references as ordinary Ref2VA inputs.

The user chose:

- RefMod should prioritize reusable assets.
- Each project should extract its own RefMods from approved assets.

## Current State

- OpenMontage's local H3 workflows use native `MiniMaxH3ReferenceToVideo` inputs such as `ref_image_0` and `ref_image_1`; the cinematic asset director does not prepare or apply RefMods.
- The ComfyUI installation has `ComfyUI-MiniMaxH3Mod`, RefMod extraction/application nodes, and an existing file under `models/refmods`. User-owned H3 RefMod workflows also exist in the shared workflows directory.
- RefMod extraction is a community ComfyUI extension step. It encodes selected references into a reusable `.safetensors` conditioning asset; a loader/apply stage injects that conditioning into H3 Ref2VA.
- MiniMax H3 exposes separate FL2VA and Ref2VA task families. The installed RefMod Apply node requires a Ref2VA checkpoint/workflow; it cannot be combined with exact FL2VA first/last-frame conditioning.
- The current RefMod node catalog is stale: the catalog lookup reports port 8188 while the running ComfyUI status reports port 8290. Validate against the actual selected server before accepting a RefMod workflow as ready.
- The cinematic assets pipeline already gates asset sheets and model selection before batch takes. This design reuses those gates.

## Goals

- Default local MiniMax H3 shot generation to project-specific RefMods for reusable approved assets.
- Store a traceable association between each Mod, its approved source assets, entity ID, and state variant.
- Apply only the Mods relevant to the current shot and keep prompt labels aligned with the H3 reference order.
- Keep exact first/last-frame shots on native FL2VA and one-off motion/video references on native Ref2VA.
- Preserve provider, model-family, and render-route approval decisions.
- Leave hosted MiniMax H3 and non-H3 providers unchanged.

## Non-goals

- Training or fine-tuning a LoRA or H3 model.
- Making RefMod mandatory for every image, shot, or hosted MiniMax H3 request.
- Reusing an unrelated pre-existing shared RefMod as an automatic match for a project entity.
- Editing user-owned workflows under `G:\ComfyUI\Shared\workflows`.
- Installing or updating third-party ComfyUI nodes as part of the default production flow.

## Approaches

### 1. Project-scoped automatic extraction — selected

After `asset_sheets` approval and once local MiniMax H3 is the approved route, extract Mods from approved reusable asset references and apply the matching Mods during shot generation. Keep Mod files under a project-specific namespace and record their provenance in project artifacts. This gives each project a stable identity library without relying on shared names. It requires a preparation step, manifest metadata, and an H3 workflow that accepts Mod bindings.

### 2. Shared library mapping

Map project entity IDs to already-installed files under `models/refmods`; fall back to native Ref2VA when no match exists. This is smaller to implement but depends on a manually maintained shared library and raises the chance of using a Mod from another project.

The user selected approach 1 because they want project-specific automatic extraction.

## Proposed Workflow

1. The normal `asset_sheets` gate approves character, clothing/state, location, and prop references.
2. If the approved route is local MiniMax H3, identify eligible assets by their stable asset/entity IDs and explicit shot references. An approved character, clothing/state, location, or prop asset is eligible when at least one planned H3 shot references it; there is no minimum number of planned uses. A transient action or camera reference without an approved asset record is not eligible. Create one Mod per approved asset/state combination so, for example, dry and wet wardrobe variants do not collapse into one reference.
3. Extract each Mod using the installed H3 RefMod nodes. Use a project-specific safe name and a stable `concept_type` (`identity`, `clothing`, `background`, or `generic` as appropriate). Never select an existing global Mod merely because its filename resembles the entity name.
4. Store the canonical `.safetensors` file under `projects/<project_id>/assets/refmods/`. Place or mirror a loader-visible copy under `models/refmods/openmontage/<project_id>/`; treat that copy as a rebuildable runtime cache. Never overwrite another project's Mod or the existing `测试人001` file.
5. Record a `metadata.refmod_assets` map in the asset manifest, keyed by source `asset_id`. Each entry records the project path, loader name, entity ID, state, concept type, source asset IDs/paths, source hashes, RefMod file hash, and extractor/model provenance.
6. For each H3 shot, pass only the Mods for the shot's referenced reusable assets. The installed `MiniMaxH3RefModTextEncode` maps the loaded Mod order to the prompt labels. Extract static approved project images with `image_refs="separate"`, so they are image-kind Mods addressed as `<Picture N>`.
7. Apply RefMods only to H3 Ref2VA workflows. Keep exact first/last-frame shots on native FL2VA, and keep one-off motion/video references as ordinary Ref2VA inputs. The installed Text Encode node accepts one RefMod bundle and cannot combine it with separate native image/video/audio reference inputs. If a shot requests both, block before submission and ask which supported Ref2VA path to keep; never drop one input or claim a unified mapping.
8. Existing projects stay unchanged until their user explicitly regenerates or opts in newly planned shots. Non-local H3 routes remain on their approved native provider path.

## Gates and Failure Behavior

- RefMod extraction runs only after the source asset sheets are approved.
- The existing model-selection gate remains authoritative. RefMod does not silently switch a hosted H3 route to local ComfyUI.
- If a shot requires both project RefMod conditioning and exact first/last-frame FL2VA conditioning, surface the incompatibility and ask which approved behavior to keep; do not silently change the operation.
- If a shot requests project RefMods together with a native Ref2VA reference, surface the installed Text Encode limitation and ask which reference path to keep; do not silently drop or combine inputs.
- Before the first extraction, validate that the selected ComfyUI server exposes the required H3 and RefMod nodes and models. Do not trust the stale 8188 node cache when the selected server is 8290.
- Validate the actual selected server's node input sockets against the extraction and application workflow contracts before extraction or batching.
- If the RefMod pack, H3 VAE/model stack, or live node validation is unavailable, mark the RefMod path blocked and surface the appropriate native H3 path for explicit user choice (FL2VA for exact first/last frames, Ref2VA for ordinary references). Do not silently fall back after RefMod was selected.
- If an approved source image, asset state, or project mapping changes, regenerate only the affected Mod and update its hash/provenance before the next batch.

## Artifact and Provenance Contract

Extend `asset_manifest.metadata` with `refmod_assets` and a project-level `refmod_usage` record. The manifest must distinguish:

- canonical project Mod path;
- loader cache path/name;
- source asset IDs and hashes;
- entity ID, state, and concept type;
- extraction node/version and H3 VAE/model stack;
- per-shot Mod IDs and their prompt-reference order.

Generated video assets continue to be recorded as the selected H3 takes. RefMod files are conditioning artifacts and should not be mislabeled as image or video assets.

## Acceptance Criteria

- A local H3 asset run with approved reusable references creates project-scoped RefMods and loads the matching Mods by asset/entity state.
- Two projects with the same character or asset label cannot overwrite or resolve each other's Mods.
- A shot receives only the Mods from its approved `references`; prompt labels and loader ordering agree.
- Exact first/last-frame shots retain native FL2VA; one-off motion/video references retain native Ref2VA conditioning.
- Hosted MiniMax H3 and other model routes do not receive local RefMod nodes or trigger a provider switch.
- An unavailable or stale RefMod setup is surfaced before batch generation and cannot silently degrade to ordinary Ref2VA.
- The asset manifest records every Mod's source and exact file hashes, and stale source assets invalidate only dependent Mods.
- Existing projects and their approved takes remain unchanged until explicitly opted in or regenerated.

## Risks and Mitigations

- **Global model-folder collisions:** use a project-specific loader namespace and retain the canonical file under the project workspace.
- **Reference-index mistakes:** use the Text Encode node's actual Mod-to-label map, extract static images as separate image-kind Mods, and reject mixed native/Mod graphs before submission.
- **State bleed:** key Mod mapping by source asset/state, and pass only the current shot's state variant.
- **ComfyUI endpoint mismatch:** refresh and validate the live node schema at the selected server URL before any workflow call.
- **Third-party node changes:** record node/version and workflow hash in provenance; fail before the batch if the live contract differs.
- **Task-family conflict:** RefMod is limited to Ref2VA; preserve exact keyframes with FL2VA and ask when a shot requires both behaviors.
- **Over-conditioning one-off motion:** preserve normal Ref2VA references for motion/video and apply Mods only to reusable concepts. The installed Text Encode route cannot combine them in one shot, so mixed requests need an explicit per-shot choice.

## Builder-Owned Details

The implementation plan may choose the exact tool boundary (a dedicated RefMod extraction tool or a narrow extension to the ComfyUI workflow tool), the manifest property substructure, and the mechanism that copies a freshly extracted file into project storage. The behavior, default scope, path isolation, failure behavior, and acceptance criteria above are the contract.

### Builder-check call

The builder asked whether a state variant used by only one planned shot should still receive a Mod. This design treats an approved catalog asset/state as reusable by identity, not by current shot count: any approved asset of an eligible kind referenced by at least one planned H3 shot gets a project Mod. This avoids adding a second reuse-count rule that would prevent a current single-shot variant from being reused when the plan expands.

This design was approved by the user on 2026-11-22. Implementation proceeds under the separate implementation plan after the user reviews that plan.
