# Video Enhancement — Pipeline Usage (Layer 2)

This is the pipeline-facing skill for **local post-enhancement of selected takes**. It decides *whether* and *which* enhancement route to run, and how the gate and re-export work. The mandatory pre-call technical reference is the Layer 3 skill at [`.agents/skills/video-enhancement/SKILL.md`](../../.agents/skills/video-enhancement/SKILL.md) — read it before calling `comfyui_enhance`.

Enhancement is an **assets-stage step**, not a compose-stage effect. It replaces the media of an already-selected take; it is not color grading, and it is not a way to rescue a take that was chosen badly. Local and API-zero-cost, but not free in time.

## The two routes and the measured trade-off

Source of evidence: `projects/_h3-api-export/STATUS.md`.

| Route | What it does | Strength | Weakness | When |
|---|---|---|---|---|
| `face_refine` (H3 FaceRefine) | Tracks and refines one face, then stitches it back with the original audio | Sharpest facial features and skin | Slight identity drift; fixes only **the largest face** in frame | One protagonist, face large enough (see below) |
| `seedvr2_upscale` (SeedVR2 3B FP8) | Whole-frame detail upscale to a target short edge (default 1080) | Most natural, identity closest to source, works on group/wide shots | Detail sharpness below FaceRefine; about **3 minutes per second of video** | Ensembles, wide shots, small faces, or when overall detail matters |
| `none` | No enhancement | Fast, safe | — | Default when unsure |

Measured SeedVR2 run: 1080×1916, 73 frames / 3.04 s, H.264 + AAC, roughly 9 minutes of processing after the ~3.16 GB first-run model download. The menu estimates SeedVR2 at `30 + 178 × duration_seconds`; FaceRefine's estimate is a placeholder.

Route → operation mapping: `face_refine` → `operation="face_refine"`, `seedvr2_upscale` → `operation="video_upscale"` (the menu row already carries this in `row["operation"]`). `none` runs nothing.

## Selection rules

1. **One dominant protagonist and the face is large enough** (guide: face height ≥ 120 px) → `face_refine`. Sample three frames before deciding; the tool does not detect or size faces.
2. **Ensemble, wide shot, small faces, no clear protagonist, or overall detail needed** → `seedvr2_upscale`.
3. **Neither is a legal choice.** `none` is always available and is the correct answer when the take is already good, the gain is marginal, or the user declines the time cost.
4. **Never use enhancement to rescue a take chosen for the wrong reason.** Re-select the take instead.
5. **The largest-face limitation must be stated to the user.** In a multi-person frame `face_refine` refines only the largest face (default `face_select="largest_face"`); every other face stays as-is. For group shots prefer `seedvr2_upscale`.
6. **Time cost is part of the choice.** Show `estimated_seconds` from the menu, state the measured SeedVR2 scale, and allow enhancing only a subset of shots. A 20-second take at SeedVR2 is roughly one hour.
7. **`face_refine` requires an approved character sheet.** Take exactly **two** reference images from that character's approved reference set: a facial close-up (node 6) and a wardrobe/full-body reference (node 7). If there is no approved character sheet, or no clear protagonist in the shot, **do not offer `face_refine`** — offer `seedvr2_upscale` or `none`. Source-led projects with no character assets default to no FaceRefine.

## Gate flow (cinematic `assets.enhancement_selection`)

The gate is defined in `pipeline_defs/cinematic.yaml` (the `assets.enhancement_selection` sub-stage) and `skills/pipelines/cinematic/asset-director.md`. It is `human_approval_default: true`, and it sits after takes are selected and before the final `asset_manifest` export. It applies to **every** cinematic assets run, source-led and narrative alike.

1. **Abilities.** Discover the registry and inspect `comfyui_enhance` (`get_status()`): when the tool status is not `available` (the server is not running or unreachable), pass `server_running=False` to `lib.local_enhancement_readiness.check_enhancement_readiness`. That report makes node-pack, model, version, and server problems known before any menu is shown. Never hide a blocked route.
2. **Menu.** Call `lib.enhancement_selection.build_menu(registry, readiness, duration_seconds=...)`. Present all three routes in order — `none`, `face_refine`, `seedvr2_upscale` — with `status`, `available`, `reason`, `warnings`, `estimated_seconds`, and `estimate_source`. A blocked route stays visible with its blockers. **Surface every row's `warnings` verbatim** — especially SeedVR2's first-run ~3.16 GB DiT download warning, which is a real part of the time cost the user is approving.
3. **Decision.** The user picks one route for the approved shot range. `build_menu` rows are **not** schema-ready `options_considered` items: they use `route_id` and carry extra keys (`status`, `available`, `warnings`, `shared_warnings`, `tool`, `operation`, `estimated_seconds`, `estimate_source`), while `record_selection` requires `option_id`, `label`, `score`, and `reason` per option and the decision schema rejects extras. Map them explicitly before calling:

   ```python
   options = [
       {
           "option_id": row["route_id"],
           "label": row["label"],
           "score": 1.0 if row["available"] else 0.0,
           "reason": row["reason"],
           **({"rejected_because": row["reason"]} if not row["available"] else {}),
       }
       for row in menu
   ]
   record_selection(path, project_id, stage, route_id, options, reason)
   ```

   Passing raw menu rows raises `ValueError` (the selectable id is absent). The decision is keyed `(category="enhancement_selection", subject="Post-enhancement route")`, is `user_visible`/`user_approved`, and is **latest-wins**: a re-entry appends a new decision covering the full current range; do not edit or reword the old one. The shot subset belongs in the `reason`/`options_considered` text.
4. **Qualification (FaceRefine only).** Before running, sample three frames with `frame_sampler` and confirm one main face at the recommended size; show the sampled frames at the gate. Pick the per-shot protagonist, take exactly two approved reference images, and write the full `subject_definitions` prompt from the approved character description plus shot context. If the face is too small, switch the decision to `seedvr2_upscale` or `none`.
5. **Apply.** Call `require_selected_route(decision_log, route_id)` (raises unless the latest approved decision matches), then `comfyui_enhance.execute(...)` per shot with `operation` from the mapping above and an `output_path` under `projects/<project_id>/assets/video/enhanced/<shot_id>-<take_id>-<operation>.mp4`. Do not run any route the user did not approve, and do not run silently.
6. **Re-export.** Call `NarrativeAssets.apply_enhancement(shot_id, take_id, path, duration_seconds=..., enhancement=...)` so the selected take's `path` becomes the enhanced file (the take id is unchanged, and the original path is preserved as `metadata.original_path`). Then regenerate `asset_manifest` and `edit_decisions`, rewrite the assets and edit checkpoints, and re-request approval. Without the re-export, `video_compose` rejects cuts whose paths no longer match the narrative selection.

## Acceptance checks

- **Audio:** stream count preserved (face_refine carries the original audio; SeedVR2 re-muxes source audio).
- **Frame rate:** unchanged (face_refine binds `23.frame_rate` to the probed source fps; SeedVR2 wires fps from the source graph).
- **Duration:** within one frame at the source fps.
- **SSIM:** `data.validation.ssim` shows a real change. Above `0.999` the tool succeeds with `output_virtually_unchanged` — surface that warning and let the user accept, change route, or skip.
- **Probe availability:** when ffprobe cannot read the downloaded output, `data.validation.warnings` contains `media_probe_unavailable`. Media validation is then skipped, but **the take is still replaced** — surface this warning and inspect the file manually before accepting it.
- **Identity:** side-by-side source vs. enhanced for FaceRefine. Identity drift is the known FaceRefine risk; if it is unacceptable, use SeedVR2 for that shot.
- **Geometry/background:** no warping, edge crawl, or flicker at batch seams (`temporal_overlap`).
- **`compose_target`:** when `seedvr2_upscale` is used, raise `edit_decisions.metadata.compose_target` to the enhanced resolution (short edge 1080, derived from the source aspect ratio, even dimensions). Composing back at 640×352 would undo the upscale and is an acceptance failure. If the user explicitly wants the original delivery resolution, skip the upscale instead.
- **Provenance:** the manifest `enhancement` object accepts only `operation`, a single `model` string, `source_path`, `parameters`, and `workflow_hash_sha256`. Put the tool result's `model` there (SeedVR2 DiT for `video_upscale`, FaceRefine UNET for `face_refine`), `source_path` = the original selected take, and `operation` from the mapping. The full `models` dict and the `workflow` filename are not allowed in the manifest — keep them in the tool result and cite them in the decision `reason`.

## Prohibitions

- **Never run enhancement silently**, outside the gate, or without an approved (`user_approved=True`) `record_selection` decision.
- **Never change identity without telling the user.** State the FaceRefine identity-drift risk and show the comparison.
- **Never treat enhancement as color grading or a creative look.** Use `color_grade`/`face_enhance` for that.
- **Never bypass `decision_log`** or edit a past decision to look like a new choice.
- **Never substitute a fallback.** There is no Real-ESRGAN/GFPGAN/FFmpeg route for this tool; a blocked route is reported, not replaced.
- **Do not re-enhance or "unify" in cleanup/compose.** Enhancement is upstream; compose must not silently re-run or undo it.
- **Do not enhance every shot by default.** Enhance only approved takes that need it; the time cost is real.

## Known boundary

`comfyui_enhance` is discoverable by every pipeline, but only the `cinematic` pipeline has the `enhancement_selection` sub-stage and the `require_selected_route` check, defined in `pipeline_defs/cinematic.yaml` and `skills/pipelines/cinematic/asset-director.md`. Other pipelines that want enhancement must add an equivalent gate; the tool itself does not enforce one.
