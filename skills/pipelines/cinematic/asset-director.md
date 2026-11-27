# Asset Director - Cinematic Pipeline

## When To Use

This stage prepares the usable media for the final cinematic edit: source selects, title-card assets, optional support inserts, music, ambience, and subtitle assets when needed.

## Animation authoring for cinematic titles and overlays

Before authoring title cards, name plates, or SVG overlays, read **`skills/meta/animation-runtime-selector.md`** for runtime routing. Cinematic pieces lean on a handful of high-craft motion patterns:

| Cinematic need | Recommended approach |
|---|---|
| Hero title with subtle reveal | Remotion `HeroTitle` component (existing) |
| Logo build / cinematic sting on SVG | GSAP DrawSVG + MotionPath — read `.agents/skills/gsap-plugins/SKILL.md` |
| Curved camera move across a wide still or overlay | GSAP MotionPath — read `.agents/skills/gsap-plugins/SKILL.md` |
| Per-character title reveal (prestige / trailer style) | GSAP SplitText — read `.agents/skills/gsap-plugins/SKILL.md` |
| Cinematic easings (Unreal-style, stuttering, weighted) | GSAP CustomEase / EasePack — read `.agents/skills/gsap-plugins/SKILL.md` |
| Name plate lower-third with elastic settle | Remotion `spring()` is usually enough; GSAP CustomEase if you need stutter |
| Film grain / particle overlay | Remotion `ParticleOverlay` (existing) |
| Color grade / LUT | `tools/enhancement/color_grade.py` (not an animation concern) |

**Cinematic is where GSAP earns its weight most often** — the genre rewards crafted easings and precise curved motion that primitive `interpolate()` struggles to express cleanly. Don't over-use it either: for a fade-in title, Remotion `spring()` still beats a whole GSAP dependency.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["scene_plan"]["scene_plan"]`, `state.artifacts["script"]["script"]`, `state.artifacts["proposal"]["proposal_packet"]` | Scene intent and beat plan |
| Tools | `subtitle_gen`, `audio_enhance`, `image_selector`, `video_selector`, `pixabay_music` (free, default), `freesound_music` (free), `music_gen` (ElevenLabs, paid) — selectors auto-discover all available providers from the registry. **Default to `pixabay_music` before reaching for `music_gen`.** | Optional support asset creation |
| Playbook | Active style playbook | Brand and typography consistency |

## Narrative Asset Pipeline — Required Order

For `narrative_generated` productions, work through this chain in order. Each step is a gate: do not advance until the previous step is locked. Read `skills/creative/narrative-consistency.md` first.

1. **Asset references.** Generate and approve the descriptor and character's five-view reference set as five separate image files, never one grid or collage: (1) shoulder-up front portrait, (2) shoulder-up side portrait, (3) front full-body without head, (4) side full-body without head, (5) back full-body with head. Keep the same identity, wardrobe/state, visual style, and background treatment across all five. Also approve the empty location plate from its master angle and recurring prop references. Record character views under `assets/references/characters/<character>/` in the declared order, and register their `role`/`path` records with `NarrativeAssets.put_asset(..., reference_images=[...])`. Record all references under `assets/references/{characters,locations,props}/`. This is the `asset_sheets` sub-stage and requires human approval.
2. **Stress test.** Run every sheet against the four bars — identity across pose/angle/light, wardrobe constancy, spatial readability, and reusability — before locking it. **A failed stress test returns to asset design**: rewrite the descriptor, regenerate the sheet or plate, retest. Do not try to fix an asset failure with more video takes; the model is not the source of the inconsistency.
3. **Optional 360° empty-scene sweep.** When coverage needs reverse angles or shot-reverse-shot, generate a slow 360° sweep of the empty location to fill in off-camera space and reduce drift when the camera crosses the axis.
4. **Video character card.** Turn each locked five-view character set into a video character card: a short moving reference clip showing the character turning, blinking, speaking, and moving in the locked wardrobe. The card is the video-model identity anchor — stills alone do not hold identity in motion generation.
5. **Model and route gate.** Before the first generation call, present the exact batch parameters — model id, resolution, duration, take count, and total cost — and confirm the approved decision with `lib.video_model_selection.require_selected_route(decision_log, route_id)`. If the route is a local H3 variant, read `proposal_packet.metadata.selected_variant`; its `runnable` flag must be true, and the variant decision must verify with `require_selected_route(decision_log, variant_id, subject=LOCAL_H3_DECISION_SUBJECT)`. Pass `checkpoint_name=variant["checkpoint_name"]` for HyperFlow, or `workflow_path=variant["workflow"]` plus `output_node=variant["output_node"]` for a stock API workflow. A UI-only workflow is a blocker: stop and show its export hint — never substitute HyperFlow for the variant the user chose. After the user confirms the batch, append a **second recorded decision** with `stage="assets"` so the gate verifies the confirmed parameters, not just the proposal pick:

   ```python
   from lib.local_h3_variants import LOCAL_H3_DECISION_SUBJECT
   from lib.video_model_selection import record_selection, require_selected_route

   proposal_metadata = state.artifacts["proposal"]["proposal_packet"]["metadata"]
   selected_route = proposal_metadata["selected_route"]
   shortlist_options = proposal_metadata["video_model_shortlist"]
   decision_log = state.artifacts["decision_log"]

   require_selected_route(decision_log, selected_route)
   record_selection(
       "projects/<project-id>/decision_log.json",
       project_id="<project-id>",
       stage="assets",
       route={"route_id": selected_route},
       options=[
           {
               "option_id": row["route_id"],
               "label": f"{row['family']} — {row['route']}",
               "score": 1.0 if row["route_id"] == selected_route else 0.5,
               "reason": row["notes"],
           }
           for row in shortlist_options
       ],  # same option_id/label/score/reason rows as proposal
       reason=f"confirmed batch: {model_id}, {resolution}, {duration}s, {takes} takes, ${total_cost}",
       subject=LOCAL_H3_DECISION_SUBJECT,  # local H3 variant; use the default subject for a route-level decision
   )
   ```

   Before presenting local H3 routes, call ComfyUI `server_info` when available and pass its `server.url` to `build_menu(registry, server_url=...)`. This refreshes local H3 readiness against the selected endpoint rather than a stale default port. If `server_info` reports `running: false` or has no `server.url`, block local H3 until a server is started; do not substitute the configured default. Only when the `server_info` tool itself is unavailable may you use the configured video ComfyUI URL, and only after its `object_info` confirms the H3 and RefMod nodes. Keep that exact URL for extraction and generation.

   This is the `model_selection` sub-stage; no approved route means no generation.
6. **Shot specs.** Write one model-neutral shot spec per shot and validate it against `schemas/artifacts/shot_spec.schema.json`: `shot_id`, `scene_id`, `duration_seconds`, `scene_context`, `references` (asset id, kind, path, role), `location_map`, `first_frame`, `format_mode`, `optics`, `camera`, `action_timing`, `physics`, `lighting`, `audio`, `character_acting`, `style`, `quality`, and `constraints`. Provider-specific parameters belong in the asset manifest, never in the shot spec.
   For shots whose `scene_id` is listed in `scene_plan.metadata.continuity_scene_ids`, include the versioned `continuity` object and register the distinct scene/shot IDs with `NarrativeAssets`. Preserve previously approved shots in unlisted legacy scenes without a continuity version.

### Strict continuity check

After the `asset_sheets` approval and once the shot specs are complete, use
`scene_plan.metadata.continuity_scene_ids` to choose strict shots. Register a
shot in a listed scene with `catalog.register_shot(shot_id, scene_id,
continuity_contract_version="1.0")`; register a grandfathered legacy shot
without a version. Before validation, persist each approved sheet with
`put_asset` using its stable `entity_id` and state, and link the sheet references
to every shot that uses them. Then call `validate_shot_continuity` before prompt
compilation and before `Batch takes`. It checks strict scenes' approved master
plates, state variants, and references; unlisted legacy scenes remain unchanged.
A missing or inconsistent reference is a pre-generation blocker, not a reason to
try a different provider.

After an enhancement changes the selected media, sample the enhanced file and
record a fresh review before re-exporting the manifest. The prior review does
not approve the enhanced media.

For each validated shot, call `build_shot_context` and pass its stable
descriptors and role-labeled reference paths into the selected provider's
Layer 3 prompt workflow. Copy the approved descriptor verbatim and use only the
shot's linked identity, location, and prop references. Provider-specific prompt
dialect and model choice remain in the existing route.

At the later assets selection gate, review representative frames for every
candidate across the five continuity dimensions and call
`catalog.record_continuity_review(shot_id, take_id, review)` before selecting.
Rejected `drift`/`unclear` candidates may be recorded without an override;
`NarrativeAssets.select_take` refuses to select them unless the user records an
explicit override reason. If enhancement changes the selected media, sample the
enhanced file and record a fresh review before re-exporting the manifest.

7. **Local H3 conditioning — project RefMod by default.** Apply this only to narrative-generated shots on a local MiniMax H3/HyperFlow route whose operation is `reference_to_video` (Ref2VA). An FL2VA-only shot using `first_last_frame_to_video` does not trigger extraction. For an existing project with a previously approved assets checkpoint or selected takes and no `refmod_usage` decision, preserve its current assets and ask for explicit opt-in before adding RefMods. After the `asset_sheets` and local `model_selection` approvals, record the conditioning choice with `record_reference_conditioning_selection(...)`: default to `project_refmod`, with `native_ref2va` as the visible alternative. If the user chooses native Ref2VA, append that choice under the same `reference_conditioning_selection` category and subject. Record the same mode and decision id with `catalog.record_refmod_usage(...)`.

   For the default project mode, visit each approved character, location, and prop asset/state referenced by at least one planned local H3 Ref2VA shot, once, in stable asset-id order. Treat wardrobe and other character states as separate character asset records; map characters to `identity`, locations to `background`, and props to `generic`, unless an approved asset explicitly supplies a `clothing` or `style` concept override. For a new five-view character asset, pass its complete approved `reference_images` role/path list to `comfyui_refmod.execute`; do not select only one view. Use the single approved `reference_path` for locations, props, and legacy single-image assets. Pass the selected `server_url`, `server_info.workspace.path`, project id/directory, asset id, selected H3 video VAE, and concept type. The tool reuses an identical current Mod; if it reports failure, stop before batching and show the blocker. Never substitute a global Mod or switch providers.

   Reload `NarrativeAssets` after extraction. For each local H3 Ref2VA shot in project mode, call `catalog.refmods_for_shot(shot_id, comfyui_workspace=server_info.workspace.path)` before `Batch takes`; a missing mapping, stale RefMod source/Mod hash, or changed loader copy blocks the batch. Build prompt labels from every returned `prompt_labels` entry and its approved descriptor, in order. These labels are global across all loaded bundles; a five-view bundle contributes five consecutive `<Picture N>` entries while using one Loader slot. Pass the same descriptors, selected `server_url`, and `comfyui_workspace` to `comfyui_video`. Each shot may use at most eight project Mods. If a shot also requires a separate native still or motion/video reference, the installed Text Encode route cannot bind both reference sets: stop and ask whether to keep the project RefMods or the native reference for that shot. Never drop either input or claim a combined mapping without a validated workflow.

   Do not send local RefMods to hosted H3 or another provider. Exact `first_last_frame_to_video` shots remain FL2VA and receive no RefMod bindings. If a shot requires both a project RefMod and exact FL2VA frames, stop before submission and ask which approved behavior to keep. If a local RefMod prerequisite fails, block the batch and offer native H3 Ref2VA for the user's explicit choice; do not fall back silently.

8. **Prompt compilation.** Compile each shot spec into the chosen model's prompt dialect — read `.agents/skills/hyperflow-h3/`, `.agents/skills/minimax-h3/`, or the matching Layer 3 skill. Copy the approved descriptor verbatim; add only scene-specific action, framing, and timing. Run the pre/post self-review below before sending anything.
9. **Batch takes.** Generate inside the **take budget** — **2–4 takes per shot**, drafted at lower resolution within the same family where possible. A weak prompt is not fixed by more takes; if none of them lands, revisit the shot spec or the asset instead of extending the budget silently.
10. **Selection.** Present the takes to the human at the assets gate, then `select_take` the approved candidate and export `asset_manifest()`.
11. **Post-enhancement gate.** After the takes are selected, run the `enhancement_selection` sub-stage through the shared **Post-enhancement gate (all cinematic runs)** section below — it is `human_approval_default: true` and no enhancement may run outside it. The step-10 `asset_manifest()` export is preliminary: the gate re-exports the manifest and renews this assets checkpoint before approval. Read `skills/creative/video-enhancement.md` first. Narrative productions add these rules to the shared gate:
    - **FaceRefine qualification.** Sample three frames with `frame_sampler`, confirm one main face at the recommended size (guide: face height ≥ 120 px), and show the frames at the gate — the tool does not detect or size faces. Choose the per-shot protagonist and take **exactly two** reference images from that character's approved set in `assets/references/characters/<character>/`: a facial close-up and a wardrobe/full-body reference. Write the full `subject_definitions` prompt from the approved character description plus shot context. No approved character sheet, no clear protagonist, or a multi-person frame means FaceRefine is not offered for that shot — offer `relayvsr_upscale`, `seedvr2_upscale` or `none` instead.
    - **Approved sheets are the only source.** FaceRefine references must come from an approved character sheet; narrative runs never offer it on an unapproved or missing sheet. Source-led runs withhold FaceRefine entirely (see the shared gate).

## Process

### Explicit 3D-world path

When the approved delivery promise is a continuous, free-viewpoint 3D world,
`threejs_world` satisfies semantic planning and browser-native motion: it creates
a real scene graph and time-driven camera, not a still-image fallback. Read
`skills/creative/3d-world-generation.md` and `.agents/skills/threejs-world-generation/SKILL.md`,
build into `projects/<id>/hyperframes/`, and review global, regional, walk,
semantic, and wireframe views before the assets gate. Keep
`render_runtime="hyperframes"` and `composition_mode="atelier"` locked for a
browser-native deliverable. For reference-grade video, lock Blender as the 3D
renderer and `render_runtime="ffmpeg"` solely as the image-sequence/audio packager.

For hero/reference-driven work, `quality_tier="production"` is mandatory. Install licensed catalogs with `threejs_asset_catalog`, generate unique meshes with Atlas/fal when useful, assemble and render in Blender, and reject the asset gate if dominant primitives, flat untextured ground, low regional object density, or obvious repetition remain. `blockout` exists only for layout/camera approval.

### 1. Prioritize Source Selects

Start with:

- source footage selects,
- stills,
- title-card backgrounds,
- any approved provided music or ambient beds.

These are the primary materials. Everything else is support.

If `proposal_packet.metadata.motion_required = true`, actual moving footage or generated video clips are mandatory. In that case:

- stills may be used only as reference material or backing elements inside a larger motion composition,
- stills may not replace the planned motion shots,
- a still-image teaser is not an acceptable fallback unless the user explicitly approves an animatic.

### 1b. Sample Preview (Prevents Wasted Spend)

Before batch-generating support assets, produce one sample of each expensive generated type and show the user:

1. **Generated insert sample** (if using `image_selector` or `video_selector`): Generate one representative visual. Confirm it complements the source footage before batching.
2. **Music sample** (try `pixabay_music` first — free, searchable by mood/BPM; fall back to `freesound_music` for cues and ambience; only reach for `music_gen` when the search tools miss the brief): sample or retrieve a short clip. Confirm mood and energy match the beat plan.

If `motion_required = true`, the representative visual must be a video clip sample, not a still image sample.

If rejected, adjust parameters and retry (max 3 iterations). Do not batch until approved.

Before the sample is generated, tell the user exactly which generation path will be used:

- tool,
- provider,
- model or variant,
- generation mode,
- why it was selected.

If that path fails, stop and ask before trying a different provider, model, or generation mode.

### 2. Generate Support Assets Only Where Needed

#### Narrative productions with reusable visual assets

When the approved brief calls for a character-led film, use the script and
scene plan to identify recurring characters, locations and props before
generating shots. Record each asset's description, approved reference image,
and relevant states (for example costume, damage, or time of day) in the
project's asset records. Keep the scene and shot links so later shots can reuse
the correct state. Review representative poses, lighting and interactions
before treating an identity as stable.

For each shot, specify the opening frame, positions and eyelines, visible
action, camera and lighting, using only the relevant approved assets. Generate
and review candidate clips, recording the prompt, seed, model, workflow and
change made for each iteration. Select a candidate explicitly for the edit;
split an overcomplicated shot when repeated adjustments do not resolve it.
Adapt the amount and format of prompt detail to the selected model rather than
assuming a Seedance-specific prompt is suitable for MiniMax H3.

If the approved path uses ComfyUI, `comfyui_image` may create the references
and `comfyui_video` with `model_family: minimax_h3_local` may generate clips.
The latter requires a locally installed H3 model stack and an API-format
workflow with an output node. Use `workflow_bindings` to inject prompt, seed,
and reference-image values into explicitly named nodes; unbound values remain
unchanged. The configured ComfyUI server may be on another machine;
do not describe the hosted H3 Partner Node as local inference. Read the
ComfyUI and MiniMax H3 skills before generating.

Persist reusable references and takes with `lib.narrative_assets.NarrativeAssets`.
Use `put_asset` for each character, location or prop state. In strict continuity
mode, assign state variants a shared `entity_id`, give the approved empty plate
`kind="location"`, `state="master_plate"`, and its stable location ID as
`entity_id`. Call `register_shot(shot_id, scene_id, continuity_contract_version="1.0")`
and then use `link_assets` to associate that shot with its approved references.
Use `add_take` for every candidate and
record its prompt, seed, model, source tool and workflow provenance in metadata.
After user review, `select_take` marks the selected take without deleting other
versions. Export `asset_manifest()` to the canonical assets artifact and pass
it through the usual validation and checkpoint process. The catalog is stored
under the project artifacts directory and does not replace the checkpoint.

For source-led projects, optional generated assets should fill clear gaps:

- missing transitional b-roll,
- concept-led inserts,
- texture or atmosphere cards,
- simple textural motion backgrounds.

For motion-required jobs, use `video_selector` first for generated shots. `image_selector` may support look development, concept frames, or embedded design layers, but it does not satisfy the motion requirement by itself.

### 3. Prepare A Real Audio Plan

Store:

- chosen music track or prompt,
- ambience layers,
- impact or transition sounds,
- subtitle assets if dialogue or narration is present.

### 4. Use Metadata For Rights And Intent

Recommended metadata keys:

- `source_selects`
- `music_plan`
- `ambience_plan`
- `title_assets`
- `generated_support_assets`
- `rights_notes`

### Pre/Post Self-Review for Generation Prompts

> Before sending a prompt to any image or video generation tool, run a three-step self-review modeled on the CHAI oversight loop ("Building a Precise Video Language with Human-AI Oversight", arXiv 2604.21718v2). Cost is small (no extra tool calls); benefit is large (avoids wasted generations). For cinematic, this matters most for **hero-frame prompts** — one bad hero frame ruins the piece, and hero frames are the most expensive shots to regenerate.
>
> **Step 1 — Pre-caption pass.** Write the prompt the way you'd write it today. Do not over-edit; aim for a complete first draft.
>
> **Step 2 — Critique pass.** Score the draft against the 5-aspect checklist (Subject / Subject Motion / Scene / Spatial Framing / Camera). For each aspect:
> - Is it specified? If not, is the omission deliberate (e.g., "no subject — scenery shot") or accidental?
> - Are confusable terms disambiguated? (dolly vs zoom, pan vs truck, bird's-eye vs aerial, fisheye vs barrel, full shot vs close-up)
> - Are emotional adjectives ("epic", "moody", "cinematic") replaced with their visual causes (low-key lighting, slow push-in, anamorphic flare, deep shadows)?
> - For multi-shot prompts and identity-anchored hero frames: is identity anchored verbatim across shots?
>
> **Step 3 — Post-caption pass.** Rewrite filling the missing aspects, fixing confusable terms, and replacing subjective language. The post-caption is what gets sent to the generation tool.
>
> Log the (pre, critique, post) triplet in the asset metadata for traceability. This mirrors the CHAI workflow and creates a record the reviewer can audit.

### 5. Quality Gate

- source and support assets are clearly distinguished,
- generated inserts are limited and purposeful,
- audio plan matches the beat map,
- every referenced file exists.
- if motion is required, the asset set contains actual video clips for the motion-led beats.

### Mid-Production Fact Verification

If you encounter uncertainty during asset generation:
- Use `web_search` to verify visual accuracy of subjects (e.g. what does this building actually look like?)
- Use `web_search` to find reference images before generating illustrations
- Log verification in the decision log: `category="visual_accuracy_check"`

Visual accuracy matters. If the script mentions a specific place, person, or object,
verify what it actually looks like before generating images. Don't rely on
the AI model's training data — it may be wrong or outdated.

## Post-enhancement gate (all cinematic runs)

Every cinematic assets run — source-led or narrative — enters the `enhancement_selection` sub-stage after the approved takes are selected and before the assets checkpoint's manifest export is final. It is `human_approval_default: true`. Read `skills/creative/video-enhancement.md` first. No enhancement may run outside this gate, and no route may be hidden, skipped silently, or substituted.

The `asset_manifest` export from take selection is **preliminary**. After the gate, re-export the manifest, rewrite the assets checkpoint (and the edit checkpoint when `edit_decisions` was regenerated), and re-request human approval. The gate is not complete until the re-exported manifest and the renewed assets checkpoint both reflect the approved route.

1. **Abilities and menu.** Discover the registry and inspect `comfyui_enhance` with `get_status()`: `unavailable` means the ComfyUI server is not running (or unreachable), so pass `server_running=False` to `lib.local_enhancement_readiness.check_enhancement_readiness`. That report covers node-pack, model, version, and server problems before anything is shown. Call `lib.enhancement_selection.build_menu(registry, readiness, duration_seconds=...)` and present every row — `none`, `face_refine`, `seedvr2_upscale`, `relayvsr_upscale` — with `available`, `status`, `reason`, `warnings`, `estimated_seconds`, and `estimate_source`. A blocked route stays visible with its blockers. **Surface each row's `warnings` verbatim at the gate**; SeedVR2's first run downloads about 3.16 GB of DiT weights, and that download is part of the time cost the user is approving. State the measured SeedVR2 scale (about 3 minutes per second of video) and that only an approved subset of shots needs to run.
2. **Who can offer what.** Source-led runs offer `none`, `relayvsr_upscale` or `seedvr2_upscale` and withhold `face_refine`, because FaceRefine requires an approved character sheet and source-led runs have no approved character reference set. Recommend RelayVSR for overall upscale when available. FaceRefine is optional for distant small faces that need it and meet the qualification and two-reference rules above.
3. **Decision.** The user picks one route for the approved shot range. Map the menu rows to schema-ready `options_considered` items (`option_id`, `label`, `score`, `reason`) before calling `lib.enhancement_selection.record_selection(path, project_id, stage, route_id, options, reason)`; raw menu rows carry extra keys and are not schema-ready. `record_selection` sets `category="enhancement_selection"` and `subject="Post-enhancement route"` internally — pass only `path`, `project_id`, `stage`, `route_id`, `options`, and `reason`. The decision is latest-wins: re-entry appends a new decision covering the full current range and never edits the old one.
4. **Apply.** Call `lib.enhancement_selection.require_selected_route(decision_log, route_id)` — it raises unless the latest approved decision matches — then `comfyui_enhance.execute(...)` per shot with the operation from the route mapping and an `output_path` under `projects/<project_id>/assets/video/enhanced/<shot_id>-<take_id>-<operation>.mp4`. Never run a route the user did not approve, and never run silently.
5. **Re-export and re-approval.** Narrative runs call `NarrativeAssets.apply_enhancement(shot_id, take_id, path, duration_seconds=..., enhancement=...)` so the selected take's media path becomes the enhanced file (the take id is unchanged and the original path is preserved as `metadata.original_path`); source-led runs update the manifest's asset path and `enhancement` provenance directly. Then regenerate `asset_manifest` and `edit_decisions` as needed, rewrite the assets (and edit) checkpoints, and re-request human approval on the assets gate. Without the re-export, `video_compose` rejects cuts whose paths no longer match the narrative selection.

## Common Pitfalls

- Generating extra shots before proving the source edit works.
- Treating music as a single loop instead of a beat-aware element.
- Forgetting rights or provenance notes for supplied assets.
- Quietly downgrading from video clips to still images because one provider or renderer failed.
- Quietly switching providers or models after the user approved a generation path.


## When You Do Not Know How

If you encounter a generation technique, provider behavior, or prompting pattern you are unsure about:

1. **Search the web** for current best practices — models and APIs change frequently, and the agent's training data may be stale
2. **Check `.agents/skills/`** for existing Layer 3 knowledge (provider-specific prompting guides, API patterns)
3. **If neither helps**, write a project-scoped skill at `projects/<project-name>/skills/<name>.md` documenting what you learned
4. **Reference source URLs** in the skill so the knowledge is traceable
5. **Log it** in the decision log: `category: "capability_extension"`, `subject: "learned technique: <name>"`

This is especially important for:
- **Video generation prompting** — models respond to specific vocabularies that change with each version
- **Image model parameters** — optimal settings for FLUX, GPT Image, Imagen differ and evolve
- **Audio provider quirks** — voice cloning, music generation, and TTS each have model-specific best practices
- **Remotion component patterns** — new composition techniques emerge as the framework evolves

Do not rely on stale knowledge. When in doubt, search first.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
