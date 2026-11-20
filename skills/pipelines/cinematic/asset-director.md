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

1. **Asset sheets.** Generate and approve the descriptor + reference image, the three-panel character sheet (face close-up, front full-body without head, back full-body), the empty location plate from the master angle, and the prop sheets. Record everything under `assets/references/{characters,locations,props}/` and link it with `lib.narrative_assets.NarrativeAssets`. This is the `asset_sheets` sub-stage and requires human approval.
2. **Stress test.** Run every sheet against the four bars — identity across pose/angle/light, wardrobe constancy, spatial readability, and reusability — before locking it. **A failed stress test returns to asset design**: rewrite the descriptor, regenerate the sheet or plate, retest. Do not try to fix an asset failure with more video takes; the model is not the source of the inconsistency.
3. **Optional 360° empty-scene sweep.** When coverage needs reverse angles or shot-reverse-shot, generate a slow 360° sweep of the empty location to fill in off-camera space and reduce drift when the camera crosses the axis.
4. **Video character card.** Turn each locked character sheet into a video character card: a short moving reference clip showing the character turning, blinking, speaking, and moving in the locked wardrobe. The card is the video-model identity anchor — stills alone do not hold identity in motion generation.
5. **Model and route gate.** Before the first generation call, present the exact batch parameters — model id, resolution, duration, take count, and total cost — and confirm the approved decision with `lib.video_model_selection.require_selected_route(decision_log, route_id)`. If the route is a local H3 variant, its `runnable` flag must be true; pass its `checkpoint_name` (HyperFlow) or `workflow_path` (stock API workflow) to the tool. A UI-only workflow is a blocker: stop and show its export hint — never substitute HyperFlow for the variant the user chose. After the user confirms the batch, append a **second recorded decision** with `stage="assets"` so the gate verifies the confirmed parameters, not just the proposal pick:

   ```python
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
   )
   ```

   This is the `model_selection` sub-stage; no approved route means no generation.
6. **Shot specs.** Write one model-neutral shot spec per shot and validate it against `schemas/artifacts/shot_spec.schema.json`: `shot_id`, `scene_id`, `duration_seconds`, `scene_context`, `references` (asset id, kind, path, role), `location_map`, `first_frame`, `format_mode`, `optics`, `camera`, `action_timing`, `physics`, `lighting`, `audio`, `character_acting`, `style`, `quality`, and `constraints`. Provider-specific parameters belong in the asset manifest, never in the shot spec.
7. **Prompt compilation.** Compile each shot spec into the chosen model's prompt dialect — read `.agents/skills/hyperflow-h3/`, `.agents/skills/minimax-h3/`, or the matching Layer 3 skill. Copy the approved descriptor verbatim; add only scene-specific action, framing, and timing. Run the pre/post self-review below before sending anything.
8. **Batch takes.** Generate inside the **take budget** — **2–4 takes per shot**, drafted at lower resolution within the same family where possible. A weak prompt is not fixed by more takes; if none of them lands, revisit the shot spec or the asset instead of extending the budget silently.
9. **Selection.** Present the takes to the human at the assets gate, then `select_take` the approved candidate and export `asset_manifest()`.

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
Use `put_asset` for each character, location or prop state; `link_assets`
associates reference IDs with a scene. Use `add_take` for every candidate and
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
