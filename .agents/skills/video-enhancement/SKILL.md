---
name: video-enhancement
description: Use before calling comfyui_enhance — the local ComfyUI post-enhancement routes (H3 FaceRefine face refinement and SeedVR2 3B FP8 video upscale). Covers the bundled workflow node IDs and bindable inputs, parameter meanings and defaults, the node-23 output contract including frame_rate binding, failure modes, and measured evidence.
---

# Video Enhancement (ComfyUI) — Layer 3

Use this skill **before** calling `comfyui_enhance`. It is the mandatory pre-call reference: node IDs, bindable inputs, output contract, failure modes, and measured evidence. For *when* and *whether* to enhance in a pipeline, read the Layer 2 skill `skills/creative/video-enhancement.md`.

This tool is local and zero-cost in API spend; the only cost is wall-clock time on the local GPU. It has **no fallback**: there is no Real-ESRGAN, GFPGAN, or FFmpeg-filter substitute. If a route cannot run, report the structured blocker rather than substituting something else.

## The two operations

| `operation` | Workflow file | Backend | Best for |
|---|---|---|---|
| `face_refine` | `enhance_face_refine_h3_api.json` | H3 FaceRefine (MiniMax H3) | One dominant, large face in frame |
| `video_upscale` | `enhance_seedvr2_3b_api.json` | SeedVR2 3B FP8 | Whole-frame detail on any shot |

Both workflows are bundled API-format graphs under `tools/_comfyui/workflows/`; see `ENHANCE_PROVENANCE.md` there for upstream sources, local patches, default model filenames, and licensing. The source video is never modified: the enhanced file is written to `output_path` (which must stay inside `project_dir`).

Route → operation mapping (the menu's `route_id` is not the tool's `operation`): `face_refine` route → `operation="face_refine"`; `seedvr2_upscale` route → `operation="video_upscale"`; `none` runs nothing. Menu rows expose the correct value as `row["operation"]`.

## FaceRefine — node map and bindable inputs

Node `"23"` (`VHS_VideoCombine`) is the only output node. The tool patches the following nodes:

| Node | Class | Bindable input(s) | Bound from |
|---|---|---|---|
| `1` | `VHS_LoadVideoPath` | `video` | Absolute source path (`input_path`) |
| `2` | `H3FaceTrackCrop` | `select`, `identity_threshold`, `detector` | `face_select`, `identity_threshold`, `models.detector` |
| `4` | `VAELoader` | `vae_name` | `models.vae_video` |
| `5` | `VAELoader` | `vae_name` | `models.vae_audio` |
| `6` | `LoadImage` | `image` | `reference_image_paths[0]` — identity close-up (uploaded) |
| `7` | `LoadImage` | `image` | `reference_image_paths[1]` — wardrobe/full-body (uploaded) |
| `9` | `MiniMaxH3ReferenceToVideo` | `prompt` | `prompt` (required, non-empty) |
| `12` | `LoraLoaderModelOnly` | `lora_name` | `models.lora` |
| `16` | `BasicScheduler` | `denoise` | `denoise` |
| `17` | `RandomNoise` | `noise_seed` | `seed` |
| `23` | `VHS_VideoCombine` | `frame_rate`, `filename_prefix` | Source fps (ffprobe) and a unique per-run prefix |
| `31` | `H3PerFrameDenoise` | `denoise_multiplier_small_face`, `denoise_multiplier_large_face` | `face_denoise_multiplier` (same value for both) |
| `108` | `UNETLoader` | `unet_name` | `models.unet` |
| `109` | `CLIPLoader` | `clip_name` | `models.clip` |

Intermediates (`10`, `13`, `14`, `15`, `18`, `19`, `22`) are graph wiring and stay fixed. Node `6` and node `7` are both required — there is **no** single-image duplication path. `face_refine` therefore requires exactly two existing reference-image paths and a non-empty prompt.

Default model filenames (all overridable through `models`): `unet=Minimax-h3_Singularity_ref2va_v2_int8.safetensors`, `clip=qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`, `vae_video=minimax_h3_video_vae_fp16.safetensors`, `vae_audio=minimax_h3_audio_vae_fp32.safetensors`, `lora=MiniMax-H3\加速\PikaFlex-Turbo-8步高清多模态参考视频加速.safetensors`, `detector=face_yolov8n.pt`.

## SeedVR2 — node map and bindable inputs

Node `"23"` (`SaveVideo`) is the only output node. The tool patches:

| Node | Class | Bindable input(s) | Bound from |
|---|---|---|---|
| `10` | `SeedVR2VideoUpscaler` | `resolution`, `max_resolution`, `batch_size`, `temporal_overlap`, `seed`, `color_correction` | Same-named inputs |
| `13` | `SeedVR2LoadVAEModel` | `model` | `models.seedvr2_vae` |
| `14` | `SeedVR2LoadDiTModel` | `model` | `models.seedvr2_dit` |
| `21` | `LoadVideo` | `file` | Uploaded source video's **server-side** filename |
| `23` | `SaveVideo` | `filename_prefix` | Unique per-run prefix |

`LoadVideo` resolves only files inside ComfyUI's input directory, so the source is uploaded and node `21` receives the uploaded name (unlike FaceRefine, which accepts an absolute path). Nodes `22` (`GetVideoComponents`) and `24` (`CreateVideo`) are fixed wiring: `24.fps` comes from `22`'s rate output and `24.audio` from `22`'s audio output, so SeedVR2 carries the source frame rate and audio through the graph.

Default model filenames: `seedvr2_dit=seedvr2_ema_3b_fp8_e4m3fn.safetensors`, `seedvr2_vae=ema_vae_fp16.safetensors`. Use the official 3B FP8 — the local 7B INT8 file is incompatible with the current SeedVR2 node (`requires_grad` / INT8 error).

## Parameter reference

| Input | Default | Node | Meaning / guidance |
|---|---|---|---|
| `denoise` | `0.4` | FaceRefine `16` | The key FaceRefine dial. **Measured** on the smoke clip at 0.2 / 0.3 / 0.4 / 0.5 with the same refs, prompt and seed (face-crop sheet: `projects/hyperflow-pilot/renders/_preview/facerefine-denoise-face-sheet.png`): **0.2** subtle sharpening, identity and head pose closest to source; **0.3** clearly sharper, minor pose/identity shift, the practical identity-sensitive default; **0.4** visibly sharper but the face reads as a similar different person and the head can turn toward camera at clip start; **0.5** no sharpness gain over 0.4, more drift. SSIM vs source: 0.991 / 0.990 / 0.989 / 0.988. For hero faces start at **0.25–0.3**; use 0.4 only when sharpness matters more than identity and the user has compared frames. |
| `face_select` | `largest_face` | FaceRefine `2` | Which face the tracker crops. `largest_face` fixes only the largest face in frame; everyone else is untouched. `select_index` is not exposed by the tool; the bundled default is `0`. |
| `identity_threshold` | `0.28` | FaceRefine `2` | Insightface tracking threshold. Lower is more permissive across occlusion/turns; higher keeps a stricter identity lock. |
| `face_denoise_multiplier` | `1.0` | FaceRefine `31` | Multiplies denoise for both small and large faces. Keep `1.0` for faces around ~180 px; lower it for very large faces to avoid over-refining. |
| `resolution` | `1080` | SeedVR2 `10` | Target **short-edge** resolution. 1080 = 1080p-class output. |
| `max_resolution` | `0` | SeedVR2 `10` | Extra cap on the long edge; `0` means no extra cap. |
| `batch_size` | `5` | SeedVR2 `10` | Temporal batch size. Larger uses more VRAM; lower it on lower-VRAM machines. |
| `temporal_overlap` | `3` | SeedVR2 `10` | Frames shared between adjacent batches; higher reduces flicker at batch seams at a time cost. |
| `color_correction` | `lab` | SeedVR2 `10` | Post-upscale color reconciliation: `lab`, `wavelet`, or `none`. `lab` is the safe default; `none` only when the source already matches. |
| `seed` | `42` | Both | Sampling seed, recorded for reproducibility. |
| `timeout_seconds` | `7200` | Client | Budget for the long-running job, not a quality parameter. |

## Output contract

- **Output node is `"23"` for both operations.** The client downloads from that node; do not pass another saver.
- **`23.frame_rate` (FaceRefine) must be bound to the source fps** read by ffprobe. The bundled default of `24` is a placeholder only. Never let a non-24 fps source run against the 24 fps default — it silently retimes the output. If ffprobe cannot supply fps **and** duration, `face_refine` refuses to run; install/fix ffprobe and retry instead of accepting a 24 fps fallback.
- **Audio is carried by the source.** FaceRefine node `23` takes audio from node `1`'s audio output (original audio); SeedVR2 node `24` takes audio from node `22`. The tool validates that the output's audio-stream count equals the source's and fails on a change.
- **Media validation before replacement:** output fps must match the source within `0.01`; duration must match within one frame (`1 / fps`); an empty or missing output fails. A `.partial.mp4` sibling is used and only a validated artifact is moved into place, so an existing output is never overwritten by a failed run.
- **Probe-unavailable warning:** when ffprobe cannot read the downloaded output, `data.validation.warnings` gets `media_probe_unavailable`. Validation is then skipped, but the run still succeeds and **the take is still replaced** — the gate must surface the warning and require a manual inspect before accepting the file.
- **SSIM is measured** across the whole clip (output scaled back to source dimensions first, so an upscale is comparable). It is reported in `data.validation.ssim`. A mean SSIM above `0.999` adds the warning `output_virtually_unchanged` — this usually means no face was detected or the enhancement had no effect. It is **success with a warning**, not a failure; the gate must show it and let the user decide.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| Unavailable / connection error | ComfyUI server not running | Start ComfyUI; set `COMFYUI_ENHANCE_SERVER_URL`, or the shared `COMFYUI_SERVER_URL` (default `http://localhost:8188`). The tool never auto-starts the server. |
| Missing custom node pack | FaceRefine needs `ComfyUI-H3-FaceRefine` **and** `comfyui-videohelpersuite`; SeedVR2 needs `seedvr2_videoupscaler` | Install the pack (ComfyUI Manager or upstream repo), restart ComfyUI. Node-directory matching is case-insensitive. |
| Missing FaceRefine model | UNET / CLIP / video VAE / audio VAE / LoRA / detector absent | Blocker. Install the listed files into the expected model folders; the readiness report names the missing file and search roots. |
| Missing `insightface` model | No `insightface` directory in model roots | Warning only — identity tracking degrades but the route is still ready. |
| Missing SeedVR2 VAE | `ema_vae_fp16.safetensors` absent | Blocker. |
| Missing SeedVR2 DiT | `seedvr2_ema_3b_fp8_e4m3fn.safetensors` absent | Warning: the node auto-downloads about 3.16 GB on first run. A failure surfaces the node's own error text. |
| SSIM unchanged (`> 0.999`) | No face found, face too small, or denoise too low | Show `output_virtually_unchanged`; do not silently accept. Re-check the source has one dominant face or raise `denoise` within safe limits. |
| Non-24 fps source | `23.frame_rate` would fall back to 24 | Bind the probed source fps. For `face_refine`, a source that cannot be probed (fps or duration missing) is a hard error. |
| Reference/image validation error | Not exactly two refs, missing file, or empty prompt | Supply exactly two existing reference images and a non-empty `prompt`. |
| Output media validation error | Audio streams, fps, or duration changed, or the output is empty | Do not replace the take. Inspect the ComfyUI server-side output and the error; retry from the source. |
| Output probe unavailable (`media_probe_unavailable`) | ffprobe cannot read the downloaded output | Success with a warning; media validation was skipped but the take was replaced. Surface the warning and inspect the file manually before accepting it. |
| `output_path` rejected | Path escapes `project_dir` | Write under `projects/<project_id>/` (for example `assets/video/enhanced/`). |

Quality limits the tool cannot measure: face presence/size, identity drift, and geometric wobble need a human/agent side-by-side check. Sample frames before running (see the Layer 2 gate) — the tool does not detect or size faces.

## Time estimates

The menu uses these formulas (`estimated_seconds`):

- `seedvr2_upscale`: `30 + 178 × duration_seconds` (`estimate_source="measured_scale"`, from the measured run below).
- `face_refine`: `120 + 60 × duration_seconds` (`estimate_source="placeholder"` — no precise timing was captured).
- `none`: `0`.

A 20-second SeedVR2 job is therefore roughly one hour. Prefer enhancing only the selected takes that need it; do not default to the whole project.

## Measured evidence

From `projects/_h3-api-export/STATUS.md` (local machine, H3 FaceRefine + SeedVR2 3B FP8):

| Route | Result | Notes |
|---|---|---|
| **FaceRefine** (official H3) | Sharpest facial features and skin | Slight identity drift. Source was a 0.7 MP medium-wide 3-second clip. |
| **SeedVR2 3B FP8** | Most natural overall, identity closest to the source | Detail sharpness below FaceRefine. Output 1080×1916, 73 frames, 3.04 s, H.264 + AAC; ~9 minutes of processing (excluding the ~1 hour, 3.16 GB first-run model download). |

FaceRefine-Plus (RTX VSR path) is blocked on this machine: `nvidia-vfx` has no cp313 wheel for the ComfyUI Python 3.13 environment. Do not promise FaceRefine-Plus, RTX VSR, or the Plus V1 workflow.

## Decision gate is upstream of this tool

`comfyui_enhance` does **not** accept a decision log and does not check route approval. The `cinematic` pipeline's `enhancement_selection` sub-stage owns that gate through `lib/enhancement_selection.py`: `build_menu` → user-approved `record_selection` → `require_selected_route` → execute. The gate is defined in `pipeline_defs/cinematic.yaml` and `skills/pipelines/cinematic/asset-director.md`. Other pipelines can discover the tool, but none has the gate yet — that is a known boundary. Never run enhancement silently or outside the gate.

## Pre-call checklist

- [ ] `operation` matches the shot: one dominant face → `face_refine`; everything else → `video_upscale`.
- [ ] Readiness checked (`check_enhancement_readiness`) and the route is `ready`; blockers shown to the user.
- [ ] For `face_refine`: exactly two existing reference images (identity close-up + wardrobe/full-body) and a non-empty `prompt` with the full subject description.
- [ ] `output_path` stays inside `project_dir`, under `assets/video/enhanced/`.
- [ ] Source frame rate and duration are probeable (ffprobe present) so `23.frame_rate` binds correctly.
- [ ] Long runtime budgeted (`timeout_seconds`); the user knows the estimated wall-clock time.
- [ ] Result inspected: audio, fps, duration, SSIM, identity, geometry; `output_virtually_unchanged` surfaced if present.

## Provenance and licensing

- The asset manifest's `enhancement` object accepts only `operation`, a single `model` string, `source_path`, `parameters`, and `workflow_hash_sha256`. Map it from the tool result: `operation` = the executed operation; `model` = the single `ToolResult.model` (FaceRefine UNET or SeedVR2 DiT); `source_path` = the original selected take; `parameters` = `provenance.parameters`; `workflow_hash_sha256` = `provenance.workflow_hash_sha256`.
- The full `provenance.models` dict and the `workflow` filename do **not** fit the manifest schema (`additionalProperties: false`). Keep them in the tool result and cite the model filenames in the decision `reason` instead of dropping them.
- H3 FaceRefine is driven by MiniMax H3 weights under the **MiniMax H3 Community License**; use in the EU, UK, South Korea, and the US requires MiniMax authorization. The `ComfyUI-H3-FaceRefine` code itself is MIT.
- SeedVR2 code is Apache-2.0; its weights follow the upstream model terms. The repository bundles workflow JSON only — no weights or media.
