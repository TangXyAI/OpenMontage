# HyperFlow Pilot — Hell Grind Scene 73.6 — 2026-11-19

Local end-to-end pilot for the Hell-Grind integration (Task 14e). Purpose: take
the HyperFlow H3 INT8 route from approved image references through a selection
gate, an FFmpeg edit, and a verified 20-second final render, and record what the
local path actually delivers.

## Project

- Project: `hyperflow-pilot` (pipeline `cinematic`, branch `feat/hell-grind-integration`)
- Scene: Hell Grind Scene 73.6 (orphanage courtyard, late golden hour)
- Concept: `c1` — "The Tackle". Three cuts in available light at child height:
  the sprint and tackle, the grass-level pin, and Roco's laugh rising into the
  held wide as the light leaves.
- Route: local MiniMax H3 HyperFlow INT8 reference-to-video
  - `comfyui_video` at `http://127.0.0.1:8188` (ComfyUI 0.45.0, RTX 4070 Ti SUPER 16 GB)
  - Checkpoint `minimax_h3_ref2va_hyperflow_flash_14b-int8_convrot.safetensors`
  - `HyperFlowLoader`, `reference_to_video`, 6 steps, native audio
  - Two reference images per shot, drawn from archive frames (`char-young-roco`,
    `char-young-jax`, `loc-orphanage-courtyard`)
- Delivery: 640x352, 24 fps source clips, six candidate takes, user-selected
  `take1` for all three shots.

## Generation metrics

| Metric | Value |
|---|---|
| Takes generated | 6 (two per shot) |
| First-try success | 6/6 |
| Batch wall time | 8.3 min (six prompts, models already loaded) |
| Peak VRAM | 15,569 MiB of 16,376 MiB (271 nvidia-smi samples at 2 s) |
| Cost | $0.00 (local weights, no API spend) |
| Source resolution | 640x352, 24 fps, one AAC audio stream |

Per-take wall seconds: s1-take1 94.4, s1-take2 82.4, s2-take1 70.4,
s2-take2 70.3, s3-take1 82.4, s3-take2 82.3. No take failed, was retried, or
hit OOM.

## Selection

The assets gate was held open with all six takes as candidates. The user
selected:

| Shot | Selected | Source duration |
|---|---|---|
| s1 | `take1` | 7.292 s |
| s2 | `take1` | 6.583 s |
| s3 | `take1` | 7.292 s |

Selection is stored in `artifacts/narrative_assets.json`, exported to
`artifacts/asset_manifest.json` (`narrative_selection` s1/s2/s3 = take1), and
approved in `checkpoint_assets.json` (`completed`, `human_approved: true`).
Decision log entry `d-008` records the assets-stage batch confirmation:
category `provider_selection`, subject `Video model and route`, selected
`hyperflow_int8`, `user_approved: true`.

## Edit

Hard cuts only, in s1 -> s2 -> s3 order, trimmed from the first frame of each
selected take. Native take audio is concatenated with the picture; no
narration, music, or SFX was added.

| Cut | In | Out | Duration |
|---|---|---|---|
| s1 | 0.0 s | 7.0 s | 7.0 s |
| s2 | 0.0 s | 6.0 s | 6.0 s |
| s3 | 0.0 s | 7.0 s | 7.0 s |
| **Total** | | | **20.0 s** |

`render_runtime: "ffmpeg"`, `renderer_family: "cinematic-trailer"`,
`composition_mode: "templated"`. Cleanup, color, and sound passes are recorded
as complete in `edit_decisions.metadata.post_passes` (review-only; no corrective
filters, grade, or mix changes applied).

## Final render

- Path: `projects/hyperflow-pilot/renders/final.mp4`
- Compose: `video_compose` `operation="render"`, `project_dir="projects/hyperflow-pilot"`,
  `render_runtime="ffmpeg"`, FFmpeg compose path
- Duration: 20.02 s (target 20.0 s, 0.1% drift)
- Streams:
  - video: h264, 640x352, 30 fps, 600 frames, ~883 kb/s
  - audio: aac, 48 kHz, stereo, ~193 kb/s
- File size: 2,713,680 bytes
- Final review: `pass` — no black frames, missing assets, or broken overlays;
  `runtime_swap_detected: false`, `delivery_promise_honored: true`.

The compose pass normalises every segment to 30 fps, so the deliverable is
30 fps even though the generated takes are native 24 fps. No other frame or
audio parameter changed.

## Known limitations

1. **Single-still identity references.** Every character and the location use a
   single archive frame, not a three-image character sheet;
   `validate_character_sheet` was not called. Identity holds in this pilot but
   is not sheet-validated.
2. **Rein and Lulu are unbound.** The approved ref2v route carries two images
   per shot. `char-young-rein` was never bound to a take, and Lulu has no
   catalog entry; both girls appear only as background figures shaped by prompt
   text, not by a reference image.
3. **s3 angle.** The courtyard reference is a populated master-angle wide whose
   held-wide landing axis is roughly 90 degrees off; off-axis reverse coverage
   is thin, so the s3 rise lands on the master geography rather than a fresh
   reverse.
4. **Duration rounding.** Source durations are 7.292 / 6.583 / 7.292 s rather
   than the requested 7.0 / 6.0 / 7.0 s because the model path rounds frame
   counts to multiples that yield 175 and 158 frames. The edit absorbs this by
   trimming to 7.0 / 6.0 / 7.0 s; the s2 take loses its rounding tail, not a
   story beat.
5. **No STT check.** The piece is dialogue-free and no transcript was
   supplied, so `transcript_comparison` was skipped; audio was judged only by
   the spotcheck and by ear. There is no word-level verification of the
   diegetic track.

## Verdict

The local HyperFlow INT8 route produced six usable takes first-try at $0 with
native audio, and the FFmpeg compose path delivered a verified 20-second
640x352 cut. The route is fit for pilot work; sheet-validated identities,
Rein/Lulu binding, and reverse coverage are the gaps to close before a
production pass.
