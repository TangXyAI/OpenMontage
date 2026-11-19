# Scene Director - Cinematic Pipeline

## When To Use

You are deciding how each cinematic beat will look and transition. This is where mood becomes a visual plan.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/scene_plan.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["script"]["script"]`, `state.artifacts["proposal"]["proposal_packet"]` | Beat map and source truth |
| Tools | `frame_sampler`, `scene_detect` | Source inspection and reframing checks |
| Playbook | Active style playbook | Color and typography consistency |

## Process

When a user supplies a scene plan, preserve scene IDs and content; validate it
and request the normal scene-plan approval after the approved script stage.
For `narrative_generated`, identify each shot's asset states and references,
opening positions, eyelines, observable acting, camera, light and sound. Record
only details relevant to that shot. Generated shots can carry the story when
the approved proposal chooses this treatment. For `source_led`, source footage
remains primary as described below; do not change existing projects' treatment.

### 1. Make Hero Frames Explicit

Every cinematic piece needs a few memorable frames. Define them directly:

- opening image,
- reveal image,
- final image,
- any title-card hero moments.

### 2. Keep Source-Led Scenes Primary

If source footage exists, let it carry the piece. Generated inserts or text cards should support transitions, emphasis, or missing coverage, not dominate the timeline.

### 3. Limit Transition Vocabulary

Choose a small set:

- hard cut,
- fade to black,
- slow dissolve,
- restrained push or punch-in.

Too many transition types kill the mood.

### 4. Use Metadata For Visual Rules

Recommended metadata keys:

- `hero_frames`
- `transition_rules`
- `aspect_ratio_rules`
- `title_card_rules`
- `support_insert_rules`

### 5. Declare `required_assets` And `location_map`

Every scene in `scene_plan.scenes[]` must carry a `required_assets` array. Each item must match `schemas/artifacts/scene_plan.schema.json` exactly:

- **`type`** — the asset class (for example `character`, `location`, `prop`, `reference`).
- **`description`** — the stable text the asset sheet is generated from; for characters this is the descriptor copied verbatim into shot prompts.
- **`source`** — one of `generate`, `source`, `provided`, or `record`. (`existing` and `reference` are not valid enum values.)

For `narrative_generated`, this list is the input to the asset-sheet gate; an asset that is not listed cannot be generated for the shot.

`location_map` is **not** a scene field — scene objects have `additionalProperties: false`. Record it in the open root `metadata` object, keyed by scene id:

```json
{
  "metadata": {
    "location_map": {
      "s02": "Locked master angle from the door; table center-frame; window camera-left; single key light through the window, shadow falls right."
    }
  }
}
```

Each value is one string describing the locked master angle, named anchor objects (door, window, table, skyline), camera-relative positions, and the single light source and shadow direction. Copy the matching string into that scene's shots' `shot_spec.location_map`, so the location plate, the shot spec, and the take share one spatial contract. The asset director builds the empty location plate from it.

Every shot also needs a stable **shot id** (`shot_id`). The id is the key later stages use for shot specs (`schemas/artifacts/shot_spec.schema.json`), take selection, and edit decisions — a shot without an id cannot be tracked through the assets gate. Use a scene-prefixed form such as `s02-sh03`.

### 6. 5-Aspect Scene-Plan Checklist

> Every scene beat — and especially every hero frame — must specify all five aspects. Cinematic relies on a small number of memorable frames; vague hero-frame specs are the single most common failure mode and produce unpredictable model output. Marking an aspect as N/A is allowed but must be explicit (e.g., "no subject — establishing scenery shot"). Silent omission is forbidden.
>
> 1. **Subject** — type + key visual attributes; if multiple, how to disambiguate. For hero frames, identity must be anchored verbatim across shots.
> 2. **Subject Motion** — actions in temporal order; subject↔object / subject↔subject interactions.
> 3. **Scene** — overlays (separately!) + POV + setting + time of day + scene dynamics.
> 4. **Spatial Framing** — shot size + position-in-frame + depth (FG/MG/BG) + camera-height-relative; and how those CHANGE across the beat.
> 5. **Camera** — playback speed → lens distortion → height → angle → focus/DoF → steadiness → movement.
>
> See `skills/creative/video-gen-prompting.md` for the primitive vocabulary.

> **Overlays callout.** Overlays (titles, subtitles, HUD, watermarks, framing graphics, lower-thirds, name plates, end-tag cards) are NOT part of the scene's foreground/midground/background depth axis. List them separately in scene metadata (`overlays: [...]`) with content and placement. Never describe an overlay as "in the foreground" — that confuses both downstream tools and any video-understanding model that re-analyzes the output.

### 7. Quality Gate

- every scene declares `required_assets` with `type`, `description`, and a valid `source`,
- every scene id has an entry in `scene_plan.metadata.location_map`,
- every shot has a stable `shot_id` and carries its scene's `location_map` string,
- every beat has a scene treatment,
- hero frames are identifiable AND fully specified across all 5 aspects,
- support inserts are justified,
- overlays are recorded under `overlays:`, never inside the depth/framing description,
- the visual language stays consistent across the piece.

## Common Pitfalls

- Using title cards as filler.
- Treating generated inserts like the primary story without saying so.
- Planning flashy transitions for every beat.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
