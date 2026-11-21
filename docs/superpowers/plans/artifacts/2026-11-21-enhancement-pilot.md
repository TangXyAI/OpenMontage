# Enhancement Pilot Report — 2026-11-21

Status: **measured**. This is the operational run for the local post-enhancement
feature (Task 10). Every number below comes from the tool results, `ffprobe`, or
`nvidia-smi` sampling on the pilot machine; anything inferred is labelled as such.

## Environment

| Item | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 4070 Ti SUPER, 16,376 MiB, driver 617.14 |
| ComfyUI | 0.45.0 at `http://127.0.0.1:8188` (Python 3.13.12, torch 2.13.0+cu130) |
| ComfyUI install | `G:/ComfyUI/Installs/ComfyUI/ComfyUI` |
| Model roots checked | `G:/ComfyUI/Shared/models`, `G:/ComfyUI/Installs/ComfyUI/ComfyUI/models` |
| FFmpeg / ffprobe | 9.0.2-full_build (gyan.dev) |
| Repo runtime | `D:/AI/OpenMontage/.venv/Scripts/python.exe` (Python 3.11.14) |
| Worktree | `.claude/worktrees/feat-video-enhancement`; pilot copied to `projects/hyperflow-pilot` |
| Cost | $0.00 (local weights, no API spend) |

Readiness (`check_enhancement_readiness`, `server_running=True`):

- `ready: true`, `ready_routes: ["face_refine", "video_upscale"]`
- All 13 checks `ok` (ComfyUI version >= 0.43.0, both custom node packs, every
  FaceRefine and SeedVR2 model file)
- `blockers: []`, `warnings: []`

## Commands

Both GPU jobs were run through the real tool, sequentially (16 GB VRAM), with
`timeout_seconds=3600` and a 3 s `nvidia-smi` sampler alongside:

```python
from tools.enhancement.comfyui_enhance import ComfyUIEnhance

ComfyUIEnhance().execute({
    "operation": "video_upscale",
    "input_path": "projects/hyperflow-pilot/assets/video/s1-take1.mp4",
    "output_path": "projects/hyperflow-pilot/assets/video/enhanced/s1-take1-upscale.mp4",
    "project_dir": "projects/hyperflow-pilot",
    "resolution": 1080, "batch_size": 5, "temporal_overlap": 3,
    "timeout_seconds": 3600,
})
```

```python
result = ComfyUIEnhance().execute({
    "operation": "face_refine",
    "input_path": "G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_face_source_07mp.mp4",
    "output_path": "projects/hyperflow-pilot/assets/video/enhanced/smoke-face-refine.mp4",
    "project_dir": "projects/hyperflow-pilot",
    "reference_image_paths": [
        "G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_ref_cui_zhu.png",
        "G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_ref_cui_zhu_wardrobe.png",
    ],
    "prompt": source_prompt,   # node "2".inputs.value of smoke_singularity_ref2v.api.json
    "denoise": 0.4,
    "timeout_seconds": 3600,
})
```

Integration used `NarrativeAssets.apply_enhancement`, `write_checkpoint`, and
`lib.enhancement_selection.record_selection`; the render used
`VideoCompose().execute({"operation": "render", "render_runtime": "ffmpeg", ...})`.

## SeedVR2 3B FP8 — `s1-take1`

| Metric | Value |
|---|---|
| Input | `assets/video/s1-take1.mp4` — 640x352, 24 fps, 175 frames, 7.292 s, 3.28 MB |
| Parameters | resolution 1080, batch 5, overlap 3, color `lab`, seed 42, max_resolution 0 |
| Workflow hash | `302e60eea262f50ad57b42fb879f399be48bfa2f068531439b893271c7a00ac5` |
| ComfyUI execution | 1,168.9 s (19 min 29 s) |
| Download | 2.2 s |
| **Wall time** | **1,178.6 s (19 min 39 s)** — 161x realtime |
| Peak VRAM | 13,539 MiB of 16,376 MiB (82.7%), 387 samples at 3 s |
| Output | 1962x1080, 24 fps, 175 frames, 7.292 s, H.264 + AAC stereo, 19,322,241 B (21.2 Mbps) |
| Audio | 1 stream, preserved (same count as source) |
| SSIM vs source | **0.940630** (Y 0.918629, U 0.981870, V 0.987397), independently reproduced with the bundled `ssim` filter |
| Validation warnings | none |

Frame inspection (1.0 s and 3.5 s, source scaled to 1962x1080 for comparison):
clover, brick courses and window mullions resolve far more finely; faces and
wardrobe stay recognisably the same people; the golden-hour grade is preserved
with a slightly cleaner, less grainy surface.

Aspect: SeedVR2 rounds the long edge to an even pixel, so 640x352 (1.8182)
becomes 1962x1080 (1.8167) — 0.08% narrower. The one-pixel difference is
absorbed by the compose target's `pad` fit.

## H3 FaceRefine — smoke clip

| Metric | Value |
|---|---|
| Input | `smoke_face_source_07mp.mp4` — 640x1136, 24 fps, 73 frames, 3.042 s, 752,700 B |
| References | `smoke_ref_cui_zhu.png` (identity), `smoke_ref_cui_zhu_wardrobe.png` (wardrobe) |
| Prompt | node `"2".inputs.value` of `projects/_h3-api-export/smoke_singularity_ref2v.api.json` |
| Parameters | denoise 0.4, `largest_face`, identity_threshold 0.28, multiplier 1.0, seed 42 |
| Models | UNET `Minimax-h3_Singularity_ref2va_v2_int8`, CLIP `qwen3vl_32b_minimax_h3_nvfp4_awq`, video/audio VAEs, PikaFlex-Turbo LoRA, `face_yolov8n.pt` |
| Workflow hash | `1b81df804a266cd015eaaaf49ccc4520ded249c70cfdd4caa7771c5c0773ec0e` |
| ComfyUI execution | 158.4 s (2 min 38 s) |
| Download | 2.0 s |
| **Wall time** | **169.4 s (2 min 49 s)** — 56x realtime |
| Peak VRAM | **15,535 MiB of 16,376 MiB (95%)** |
| Output | 640x1136, 24 fps, 73 frames, 3.042 s, H.264 + AAC, 979,125 B |
| Audio | 1 stream, preserved |
| SSIM vs source | **0.988728** (Y 0.985623), independently reproduced |
| Validation warnings | none |

Identity comparison (agent judgement on extracted frames at 0.6 s and 2.0 s):

- **Sharper:** eyes, brows, lips and skin texture are clearly more defined; the
  face is no longer soft at this 0.7 MP scale.
- **Identity drift:** the refined face reads as a *similar but different* young
  woman — wider eyes, straighter brow line, slightly narrower chin — and at
  0.6 s her head has already turned toward camera while the source still looks
  down and left. The face is sharper, not more faithful.
- The rest of the frame is re-encoded by the same H3 pass, so robe folds and
  background also gain apparent crispness; this is not a face-only pixel splice.
- This is one 3 s clip at denoise 0.4 on one machine. Treat it as directional
  evidence, not a denoise sweep.

## Pilot integration

`s1/take1` was repointed at the SeedVR2 output; `s2` and `s3` keep their
original takes and the approved 7.0 / 6.0 / 7.0 trim.

- `NarrativeAssets.apply_enhancement("s1", "take1", "assets/video/enhanced/s1-take1-upscale.mp4", duration_seconds=7.292, enhancement={operation: video_upscale, model: "SeedVR2 3B FP8 (seedvr2_ema_3b_fp8_e4m3fn.safetensors)", source_path: assets/video/s1-take1.mp4, parameters {resolution 1080, batch 5, overlap 3, color lab, seed 42}, workflow_hash_sha256: 302e60ee…})`
- `asset_manifest` regenerated: `take:s1:take1` now points at the enhanced file
  and carries the `enhancement` provenance block; `narrative_selection` stays
  `s1/s2/s3 = take1`.
- `edit_decisions` rewritten: only the `s1` cut's `source` and `reason` changed;
  the s2/s3 sources were re-rooted from the main checkout into this worktree
  copy (the pilot was authored in `D:/AI/OpenMontage/projects/hyperflow-pilot`;
  absolute paths outside the project are rejected by the narrative-selection
  guard). Trims, order and reasons are otherwise untouched.
- `metadata.compose_target` raised to `{"width": 1962, "height": 1080, "fit": "pad"}`
  from 640x352.
- Checkpoints rewritten: `assets` `completed` with `human_approval_required:
  true`, `human_approved: true`; `edit` `completed`.
- Decision log entry **`d-009`**: category `enhancement_selection`, subject
  "Post-enhancement route", options `none` (0.5) / `face_refine` (0.6, rejected —
  s1 frames four children, FaceRefine only tracks the largest face) /
  `seedvr2_upscale` (1.0), selected `seedvr2_upscale`, `user_approved: true`,
  reason "approved: s1 only; s2/s3 keep original takes".

Guard result: the render completed, which means
`VideoCompose._validate_narrative_selection` accepted the pair — catalog,
manifest, asset checkpoint and edit checkpoint all agree on `s1/s2/s3 =
take1`, and every cut resolves to its selected take inside the project. No
"narrative selection changed" or "cut source does not match" rejection fired.

## Final enhanced render

| Metric | Value |
|---|---|
| Path | `projects/hyperflow-pilot/renders/final-enhanced.mp4` |
| Runtime | `render_runtime="ffmpeg"` (unchanged from proposal; `runtime_swap_detected: false`) |
| Resolution | **1962x1080** (was 640x352) |
| Frame rate | 24 fps (480 frames) |
| Duration | 20.021 s container / 20.000 s video (target 20.0 s, 0.1% drift) |
| Audio | exactly one AAC stream, 48 kHz stereo, 943 frames |
| Codec / size | H.264 High, 5.92 Mbps, 14,827,088 B (14.1 MiB) |
| Final review | `pass` — no black frames, broken overlays, missing assets or clipping |
| Pre-compose advisory | slideshow risk 3.3/5.0 ("revise"), same advisory as the 640x352 pilot; three distinct moving shots carry the cut |

Only `s1` is natively 1962x1080. `s2` and `s3` are still 640x352 masters and are
resampled to the compose target by FFmpeg, so they are soft next to `s1`; the
resolution raise is real per-frame but not uniform across the cut.

## Test suite

`python -m pytest tests/lib tests/tools tests/contracts -q` →
**3017 passed, 7 failed, 17 skipped in 1646.97 s (27 min 26 s)**.

The 7 failures are pre-existing and unrelated to this feature:

- `tests/lib/test_terminal_frame_pacing.py::test_trace_matches_the_actual_terminal_scene_cursor`
  and `tests/tools/test_makefile_run_python_quoting.py::test_run_python_is_quoted_in_every_command_position`
  — `UnicodeDecodeError: 'gbk' codec` reading non-ASCII files under this
  machine's GBK locale.
- `tests/tools/test_showcase_card_security.py` (5 tests) — the FFmpeg binary on
  PATH (`ComfyUI-DLSS-NR/runtimes/ffmpeg-bin/ffmpeg.EXE`) crashes with
  `0xC0000005` (access violation) on `drawtext` with `textfile=`.

The latest commits touching those test files (`454bb28`, `83e4df1`) are both
ancestors of `main`, so no commit on this branch changed them. Not mixed into
the enhancement commit.

## Known limitations

1. **FaceRefine is largest-face only.** On `s1` (four children in frame) it would refine
   one child and leave the other three untouched, which is why the pilot rejected it.
   Keep it for single-dominant-face shots.
2. **Identity drift is real at denoise 0.4.** FaceRefine buys sharpness with a
   recognisable but different face, and can shift head pose at clip starts.
   Compare frames before accepting; the tool cannot measure identity.
3. **SeedVR2 time cost dominates.** 19.6 minutes for a 7.3 s take (~161x
   realtime). Enhance selected takes, never a whole project. The menu's
   `30 + 178 x duration` estimate gives 1,328 s for this take — conservative
   against the measured 1,179 s, and a fine upper bound.
4. **VRAM is tight.** FaceRefine peaked at 15,535/16,376 MiB (95%). Do not run
   the two routes concurrently on 16 GB; sequence them.
5. **Resolution gain is per-take.** Raising `compose_target` to the enhanced
   size only helps the enhanced cuts; the other cuts are upscaled by FFmpeg and
   look softer at 1080p.
6. **Even-pixel rounding.** SeedVR2 returns 1962x1080 for a 640x352 source
   (0.08% aspect change); the `pad` fit absorbs it as a one-pixel bar.
7. **Master bitrate.** 21.2 Mbps 1080p H.264 master (19.3 MB for 7.3 s) plus a
   14.1 MB 20 s render — fine for review, re-encode for delivery.
8. **Model-name portability.** The manifest records the SeedVR2 filename
   (`seedvr2_ema_3b_fp8_e4m3fn.safetensors`); another install may ship a
   different 3B FP8 file name.
9. The pilot's `artifacts/render_report.json` and `artifacts/final_review.json`
   were updated after this run to describe `final-enhanced.mp4` (1962x1080,
   14,827,088 B) and to mark the earlier 640x352 `final.mp4` as superseded;
   `renders/final.mp4` is still on disk for comparison. Both JSON files are
   gitignored and schema-validated.

## Follow-up — full 1080p pass through the real gate (2026-11-21)

After the s1-only pilot, the `assets.enhancement_selection` gate was re-entered
end-to-end exactly as `asset-director.md` describes: readiness → menu → user
selected `seedvr2_upscale` for `s2` + `s3` → decision `d-010` recorded →
per-take upscale → `apply_enhancement` → manifest/edit re-export → renewed
assets approval → recompose. `face_refine` stayed visible in the menu but was
withheld: the pilot has no approved character sheets and both shots are
multi-person frames.

| Shot | Output | Duration | SSIM | Wall |
|---|---|---|---|---|
| s2 | 1962x1080, 24 fps, one AAC | 6.584 s | 0.970181 | 1,167.8 s |
| s3 | 1962x1080, 24 fps, one AAC | 7.292 s | 0.973073 | 1,276.9 s |

- Decision: `d-010`, category `enhancement_selection`, selected
  `seedvr2_upscale`, reason "approved: s2 + s3 only; s1 already enhanced;
  face_refine withheld (no approved character sheets, multi-person frames)".
- Checks: assets `completed` with fresh approval; edit `completed`; compose
  `completed`. `require_selected_route` verified against `d-010`.
- Final: `renders/final-enhanced-all.mp4` — 1962x1080, 24 fps, 480 frames,
  20.021 s, one AAC 48 kHz stereo stream, 17,954,631 B; compose wall 14.21 s;
  final review `pass`.
- This supersedes limitation 5 above: all three selected takes are now native
  1962x1080, so no cut is an FFmpeg upscale of a 640x352 master.
