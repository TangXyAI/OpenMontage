# MiniMax H3 Multi-View Character RefMod

**Status:** Approved by user on 2026-11-27

**Scope:** Character reference preparation and local MiniMax H3 project RefMods in the cinematic pipeline.

## Intent

Prepare character references as five separate images, then encode those images as five independent picture entries in one project RefMod bundle. This gives H3 front, profile, body-proportion, wardrobe, and rear-view evidence without asking an image model to draw a collage.

The five views, in stable order, are:

1. Shoulder-up front portrait.
2. Shoulder-up side portrait.
3. Front full-body view with the head omitted.
4. Side full-body view with the head omitted.
5. Back full-body view with the head visible.

All five images belong to the same approved character and state. Each is generated, saved, reviewed, and named as its own image file. The RefMod bundle keeps these as separate picture references in that order; it does not combine their pixels into one sheet.

## Current State

- `skills/pipelines/cinematic/asset-director.md` asks for one three-panel character sheet.
- `skills/creative/narrative-consistency.md` describes three views, while `lib/narrative_assets.py::validate_character_sheet` requires exactly three existing files.
- `tools/video/comfyui_refmod.py` accepts one `reference_path`, checks it against the approved asset's single `path`, and binds one image input in `refmod_extract_api.json`.
- `NarrativeAssets` stores a single canonical asset path and RefMod source hash, so it cannot currently detect changes to a multi-image source set.
- The current extraction workflow already sets `image_refs` to `separate`, but supplies only `refs_image.ref_image_0`.

MiniMax's official H3 documentation describes Ref2VA as accepting reference images, and its hosted v2 API limits each request to nine reference images. RefMod itself is implemented by the community ComfyUI-MiniMaxH3Mod extension, whose documentation describes preserving multiple images as separate members of one version-5 bundle, loaded through one Loader slot. The hosted API image limit is not assumed to be a hard limit on OpenMontage's local RefMod route. OpenMontage will depend on the extension's bundle contract, verify the live node inputs before extraction, and use the RefMod token budget's error policy to avoid partial bundles.

## Goals

- Replace the three-panel character reference with the five specified standalone images.
- Keep the image role and order stable from generation through the RefMod bundle and H3 `<Picture N>` prompt map.
- Create one `.safetensors` RefMod bundle per approved character/state from all five images.
- Record every source image path and hash so a change to any view marks the bundle stale.
- Keep locations, props, and existing single-image character assets working with one image.
- Leave already approved three-image character sets and single-image RefMods intact; require the five-view contract only for newly generated or explicitly regenerated character sets.
- Stop with a clear blocker if the selected ComfyUI extension does not expose the five required image inputs or separate-image mode; never silently use only one view.
- Number `<Picture N>` labels dynamically across the ordered image members of every RefMod loaded for a shot. The five roles have stable positions within a character bundle, but their global numbers can shift when other assets precede them. Two five-view character bundles use two Loader slots, while all ten images remain separate entries in the local RefMod reference map.
- Do not apply the hosted API's nine-image request limit to local RefMod extraction or application without evidence that the selected local graph enforces it.

## Non-goals

- Changing the approved video provider, model family, H3 operation, or RefMod application route.
- Making five separate `.safetensors` files for each character.
- Combining views into a collage, grid, or a single stacked video-like reference.
- Requiring existing projects to regenerate already approved assets or RefMods.
- Changing image-generation providers or other asset classes.

## Constraints

- Follow the current project asset approval gate before extracting any RefMod.
- Store source images inside the project under `assets/references/characters/<character>/`; preserve project-relative paths.
- The five images must use one stable character descriptor, wardrobe/state, visual style, and background treatment.
- Keep each role explicit in filenames/catalog metadata and in the fixed order above.
- The current RefMod node is third-party software; only its documented `image_refs="separate"` mode supports the selected bundle behavior.
- Existing single-source RefMod records must continue to validate and remain current under their existing rules.

## Approaches

### 1. One multi-image bundle — selected

Extend the approved character reference set and extraction tool to pass all five images to `MiniMaxH3RefModExtract` in order, with `image_refs="separate"`. Store one RefMod per character/state and preserve the five picture members inside that bundle. This directly satisfies the user's request, uses one RefMod loader slot per character, and relies on a capability the installed extension documents.

### 2. Five separate RefMods

Extract one bundle per view and choose five RefMods at shot time. This preserves each image independently but creates five asset mappings and consumes five of the loader's eight slots for one character.

### 3. Five image files, one selected source

Save and approve all views but keep extracting from one chosen image. This minimizes tool changes but leaves four views out of the RefMod and does not use the extension's multi-image bundle support.

The user selected approach 1.

## Design

1. Generate and review the five views as distinct image files. Give each a stable role name and fixed order; do not request a multi-panel output.
2. Update the character-sheet validation contract to require exactly five distinct existing image paths. Keep the helper's descriptor check and project path checks.
3. Record the character's ordered role/path set with its approved asset. Keep a canonical primary path for legacy consumers, and preserve the full set for RefMod extraction.
4. Extend `comfyui_refmod` to accept the approved ordered set. For a new character set, require the five expected roles and paths to match the catalog. For a location, prop, or legacy single-image asset, continue to use one source image.
5. Extend the extraction API workflow with one `LoadImage` source per view, bind each source to the matching autogrow input, and keep `image_refs="separate"`. Validate all required live inputs before upload/submission.
6. Compute a deterministic source-set digest from the ordered role/path/content hashes. Persist each path and content hash in RefMod provenance. Treat the RefMod as stale if any member changes, is missing, or is reordered. Preserve validation of legacy records that contain a single `source_path` and `source_sha256`.
7. Update the asset director, narrative consistency guide, and MiniMax H3 skill with the five-view specification and stable role order. Compile global `<Picture N>` labels from the actual ordered reference map for each shot.

## Acceptance Criteria

- A new character asset requires five distinct image paths with the specified roles and order.
- The reference-generation instructions explicitly require five standalone files and reject a combined sheet.
- The extraction workflow binds all five inputs to one RefMod extraction with `image_refs="separate"`.
- The resulting project has one RefMod bundle per character/state, and its provenance identifies all five sources in order.
- Changing, deleting, or reordering any approved source makes the current bundle stale and blocks its use until re-extraction.
- The selected live ComfyUI node must support the required sockets and `image_refs` mode; an incompatible node blocks before extraction.
- Existing single-image assets, locations, props, and already approved RefMods retain current behavior.
- Existing approved three-image character sets remain valid without migration; new or regenerated character sets must meet the five-view contract.
- `<Picture N>` labels follow the actual ordered image-member map across all loaded bundles. The local path must not reject a shot solely because it contains more than nine image members; live node and token-budget constraints remain authoritative.

## Risks and Mitigations

- **Node-version drift:** validate the selected live node's inputs before extraction and surface missing support as a blocker.
- **Order mismatch:** centralize the five view-role order and use it for filenames, workflow socket bindings, provenance, and prompt labels.
- **Partial reference sets:** validate exactly five unique paths and hash all five before and after extraction; do not create a partial bundle.
- **Legacy compatibility:** retain the single-source provenance format and its freshness check for existing records.
- **Multiple bundles and labels:** number picture labels across the complete ordered set, not from 1 per bundle. Do not mistake the hosted API image cap for a local RefMod loader-slot limit; the local bundle and token-budget contracts govern.
- **Unintended collage output:** the director instructions prohibit contact sheets and the review gate verifies one view per file.

## Builder-owned Details

The implementation plan may choose the precise `NarrativeAssets` metadata key and the schema representation of the five source records, provided role, order, path, and content hash are explicit and the acceptance criteria remain true. It may also reuse the existing dynamic ComfyUI bindings or add a narrowly scoped RefMod workflow helper, whichever keeps the single-image path stable.

## Sources

- [MiniMax H3 official repository](https://github.com/MiniMax-AI/MiniMax-H3)
- [MiniMax hosted video-generation API limits](https://platform.minimax.io/docs/api-reference/video-generation-v2-create)
- [MiniMax-AI H3 integration catalog](https://github.com/MiniMax-AI/awesome-minimax-h3-integration)
- [ComfyUI-MiniMaxH3Mod multi-reference documentation](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod#multiple-references-and-merge)
