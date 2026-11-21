# Edit Director - Cinematic Pipeline

## When To Use

This stage turns the beat map into a paced cinematic timeline. Rhythm and restraint matter more than effect count.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/edit_decisions.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["assets"]["asset_manifest"]`, `state.artifacts["scene_plan"]["scene_plan"]`, `state.artifacts["script"]["script"]` | Assets, hero frames, beat map |
| Playbook | Active style playbook | Typography and transition consistency |

## Process

### 1. Cut By Emotion First

For productions using `NarrativeAssets`, call `edit_decisions(shot_ids,
render_runtime)` with the approved shot order and the already-locked render
runtime. It builds cuts from the explicitly selected takes and refuses missing
selections or files. Review and adjust trims and pacing, validate the resulting
edit decisions and write the normal edit checkpoint before composing. If a
selection changes, renew the approved assets checkpoint and write a fresh edit
checkpoint; pass the project root to compose as `project_dir`.

Cuts should follow:

- emotional emphasis,
- reveal timing,
- musical turns,
- visual contrast.

Do not optimize only for information density.

### 1b. Compose Target After Enhancement

Cuts are generated from the **updated take paths** in `NarrativeAssets`; after a take is enhanced, the cut's `source` points at the enhanced media (the take id is unchanged). Note in the cut `reason` that the take was enhanced so compose and review do not mistake it for an unprocessed source.

If the approved route was `seedvr2_upscale`, raise `edit_decisions.metadata.compose_target` to the enhanced resolution — short edge 1080, derived from the source aspect ratio, even dimensions. Composing back at the original size (for example 640×352) would squeeze the upscale back down and is an acceptance failure. If the user explicitly wants the original delivery resolution, **do not run the upscale in the first place**; never upscale and then compose at the source size.

### 2. Protect Strong Moments

If a look, line, or gesture is doing the work, let it live. Do not over-cover it with extra inserts.

### 3. Use Sound To Push The Edit

Ambience, impacts, dropouts, and music changes should help create momentum between scenes.

### 4. Use Metadata For Timing Logic

Recommended metadata keys:

- `beat_timing`
- `audio_turns`
- `title_card_windows`
- `reframe_notes`

### 5. Post Passes — Cleanup, Color, and Sound

Cinematic edits get three finishing passes before compose. Record them under `edit_decisions.metadata.post_passes` so compose can verify they ran.

- **Cleanup.** Deflicker exposure and flicker-prone generated clips, stabilise jitter where the move should be locked, remove duplicated or dead frames at take boundaries, fix popped seams between shots, and match grain across mixed sources. Cleanup never changes the editorial order — it only removes artifacts. It must not repeat or undo post-enhancement: do not re-upscale, re-sharpen, re-denoise, or re-run `FaceRefine` "for consistency". Enhancement is an upstream assets-stage step; cleanup treats the enhanced take as the source of record.
- **Color.** Grade per scene, not per clip: one scene, one look. Match black levels, white balance, and contrast across shots that came from different models or days, then apply the approved LUT or grade profile. Keep faces and text readable; refuse a grade that crushes skin tones or title cards.
- **Sound.** Balance dialogue/narration, ambience, and music explicitly — dialogue on top, ambience filling the space between cuts, music carrying the arc and dropping out for impact beats. Fix level jumps between scenes, remove clicks and take-boundary noise, and keep quiet moments quiet. No surprise silence and no flattened dynamics.

If a pass is missing or incomplete, do not advance to compose; finish it and renew the edit checkpoint.

### 6. Quality Gate

- all three post passes (cleanup, color, sound) are recorded and complete,
- the emotional arc is intact,
- reveals land clearly,
- title cards are sparse and timed with intent,
- strong moments are not buried under coverage.

## Common Pitfalls

- Overcutting emotional material.
- Using speed ramps or flashy transitions by default.
- Letting title cards replace editorial clarity.
