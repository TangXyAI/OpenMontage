---
name: hyperflow-h3
description: |
  HyperFlow — Video Rebirth's 4/6/8-step distilled MiniMax-H3 checkpoint for ComfyUI. Covers the official comfyui-hyperflow-flash and community comfyui-hyperflow-int8-nodes loaders, fl2va (t2v/i2v/flf2v) and ref2va (ref2v) INT8 and GGUF weights, API-workflow node bindings, ModelScope download sources, and the 16 GB VRAM and MiniMax H3 Community License constraints.
---

# HyperFlow H3 — Distilled MiniMax-H3 for Local ComfyUI

HyperFlow is Video Rebirth's few-step distillation of MiniMax-H3. Instead of the
base model's 20-step sampler, HyperFlow produces usable clips in **4, 6, or 8
steps at CFG 1.0**, making native H3 video+audio generation practical on a single
consumer GPU. OpenMontage routes it through the `comfyui_video` tool with
`model_family="minimax_h3_hyperflow_local"`.

Read this skill before configuring a HyperFlow run. It records the two
implementations, the exact checkpoint filenames, the API-workflow node contract,
the download sources, and the hard constraints that decide whether a local run
is viable at all.

## Two implementations

The same distilled weights can be loaded by two different ComfyUI node packs.
They are not interchangeable: the loader class, its inputs, and the available
step counts differ.

| Implementation | Node pack | Loader class(es) | Steps | Notes |
|---|---|---|---|---|
| Official HyperFlow Flash | `comfyui-hyperflow-flash` | `HyperFlowLoader` (INT8 safetensors), `HyperFlowGGUFLoader` (GGUF), plus `HyperFlowSigmas` | 4 / 6 / 8 | Reference implementation from Video Rebirth. Also accepts GGUF through the companion loader. |
| Community HyperFlow INT8 | `comfyui-hyperflow-int8-nodes` | `HyperFlowINT8Loader` | 6 | INT8-only. Ships five ready-made workflows; simplest path for a first run. |

Both packs expose the distilled sigma schedule through `HyperFlowSigmas`. The
loader output feeds the MiniMax-H3 conditioning/sampling chain the same way in
both cases; only the loader node and the sigma wiring differ.

OpenMontage's bundled API workflows in `tools/_comfyui/workflows/` ship with the
community `HyperFlowINT8Loader` and the community workflow's filenames. The tool
patches loader node `1` before submission based on `checkpoint_name` and the
`loader` argument:

- filename ends in `.gguf`, or `loader="gguf"` → `HyperFlowGGUFLoader` with
  `{"unet_name": <file>, "weights_in": "auto"}`
- filename contains `14b-int8_convrot`, or `loader="official_int8"` →
  `HyperFlowLoader` with `{"unet_name": <file>}` (no `patcher` input)
- otherwise, or `loader="community_int8"` → `HyperFlowINT8Loader` with
  `{"unet_name": <file>, "patcher": "legacy"}`

Do not hand-edit the loader node in a bundled workflow; set `checkpoint_name`
and `loader` and let the tool normalize node `1`.

## Checkpoints

HyperFlow publishes two task checkpoints. Pick the one that matches the input
contract, not the one that happens to be downloaded first.

| Variant | Supports | Use when |
|---|---|---|
| `fl2va` | text-to-video (t2v), image-to-video (i2v), first-last-frame-to-video (flf2v) | You have text, one start frame, or start+end frames. |
| `ref2va` | reference-to-video (ref2v) | You have reusable visual references or one-off native references for subject and/or setting. |

Both variants emit video **with native audio**. `fl2va` cannot take reference
images and `ref2va` cannot be used as a plain t2v checkpoint — route the
operation to the matching variant.

### Exact filenames

Place all diffusion models in `ComfyUI/models/diffusion_models/`.

| Variant | Format | Filename |
|---|---|---|
| `fl2va` | INT8 safetensors | `minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors` |
| `ref2va` | INT8 safetensors | `minimax_h3_ref2va_hyperflow_flash_14b-int8_convrot.safetensors` |
| `fl2va` | GGUF Q4_K_M | `minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf` |
| `ref2va` | GGUF Q4_K_M | `minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf` |

Approximate sizes: Q4_K_M is about 9.05 GB (`fl2va`) / 9.22 GB (`ref2va`); the
INT8 safetensors are about 16.01 GB / 16.43 GB. A Q3_K_M GGUF pair (~7.22 GB /
7.35 GB) is also published as the low-VRAM fallback — confirm the exact filename
in the ModelScope repository listing before downloading. On a 16 GB card, budget
for one checkpoint at a time, not both.

## Supporting model stack

HyperFlow replaces only the diffusion model. The rest of the MiniMax-H3 stack is
still required:

| Role | File | Location |
|---|---|---|
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` | `models/vae/` |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/` |
| Fast-workflow VAE (INT8 workflows only) | `minimax_h3_sol_vae_int8_convrot.safetensors` | `models/vae/` |
| GGUF loader | `ComfyUI-GGUF` (city96) | `custom_nodes/` |

The INT8 community workflows additionally reference the sol VAE. If it is
missing, either download it or switch to a workflow that uses the standard
video VAE — do not silently drop the node.

## Download sources

Download large checkpoints from **ModelScope** first. Hugging Face is a fallback
only; on networks where `HF_ENDPOINT` points at a mirror, verify the mirror still
serves the file before starting a multi-gigabyte transfer.

| Asset | ModelScope repository |
|---|---|
| HyperFlow `fl2va` / `ref2va` (INT8 and GGUF) | `VideoRebirthAI/hyperflow-h3-flash` |
| Text encoder and VAEs | `Comfy-Org/MiniMax-H3` |

```bash
pip install modelscope

modelscope download --model VideoRebirthAI/hyperflow-h3-flash \
  --include 'fl2va_gguf/minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf' \
  --local_dir G:/ComfyUI/Shared/downloads/hyperflow

modelscope download --model VideoRebirthAI/hyperflow-h3-flash \
  --include 'ref2va_gguf/minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf' \
  --local_dir G:/ComfyUI/Shared/downloads/hyperflow

modelscope download --model Comfy-Org/MiniMax-H3 \
  --include 'vae/minimax_h3_sol_vae_int8_convrot.safetensors' \
  --local_dir G:/ComfyUI/Shared/downloads/hyperflow
```

Move each file into the matching `models/` subdirectory after download. Never
point ComfyUI at the download staging directory.

## API workflow node contract

`comfyui_video` executes workflows in **API format** (`{"<id>": {"class_type": ...,
"inputs": ...}}`). A UI-format workflow (`nodes` / `links`) cannot be submitted —
export it to API format first. The bundled HyperFlow templates follow the node
contract below; if you author your own, keep these IDs stable so bindings work.

| Node | Class type | Inputs bound by OpenMontage |
|---|---|---|
| `1` | `HyperFlowINT8Loader` / `HyperFlowLoader` / `HyperFlowGGUFLoader` | `unet_name` (and `patcher` for the community loader) |
| `5` | `MiniMaxH3ImageToVideo` (or the reference variant's prompt node) | `prompt`, `width`, `height`, `length` |
| `6` | step-count node feeding the sigma/sampler chain | `steps` (allow 4 / 6 / 8; default 6) |
| `8` | noise node | `noise_seed` |
| `14` | `SaveVideo` | `filename_prefix`; this is the `output_node` |
| `20` | `LoadImage` | reference/first-frame `image` |
| `21` | `LoadImage` | second reference / last-frame `image` |

Operation-specific bindings:

- **text_to_video** — prompt/width/height/length on `5`; seed `8`; steps `6`;
  output `14`.
- **image_to_video** — as t2v, plus start frame on `20`/`image`.
- **first_last_frame_to_video** — start frame on `20`/`image`, end frame on
  `21`/`image`.
- **reference_to_video without RefMods** — first reference on `20`/`image`,
  second on `21`/`image`. The bundled native path requires exactly two
  `reference_image_paths`; do not submit with only one.
- **reference_to_video with project RefMods** — `MiniMaxH3RefModTextEncode` can run
  with no native still images. It loads one ordered RefMod bundle, maps visual
  Mods to `<Picture N>` while encoding the prompt, and sends that conditioning
  to H3. Each call supports up to eight mapped Mods. Exact prompt labels come
  from the ordered asset descriptors; `<Subject N>` is not a RefMod binding.
- **Native video/motion references** — use a native Ref2VA graph with named
  `reference_videos.<name>` workflow bindings. The installed RefMod Text Encode
  node does not accept separate native video references; do not combine those
  inputs with project RefMods in one shot without a different validated graph.
- **Exact first/last frames** stay on `first_last_frame_to_video` (FL2VA) and
  never receive local RefMod bindings.
- **ref2v ref bindings** — when using a reference workflow that names its inputs
  `reference_images.ref_image_0` / `reference_images.ref_image_1`, they still map
  to nodes `20` and `21`.

Local image paths are uploaded by the ComfyUI client and replaced with remote
image names before submission. Pass local paths in the tool arguments; the
workflow you inspect after upload should contain the remote names.

## Constraints and preflight

Check every item before promising a local render:

1. **ComfyUI ≥ 0.43.0** is required for native MiniMax-H3 support. Older
   versions will not load the node classes even if the packs are installed.
2. **ComfyUI-GGUF must be installed** for any `.gguf` checkpoint, and the server
   should be launched with **`--fast-disk`** so GGUF weights stream from disk
   instead of being copied into RAM. Without it, expect stalls or OOM.
3. **VRAM:** the official INT8 package has been reported at roughly **24.2 GB
   peak on an RTX 5090**. A **16 GB** card (for example an RTX 4070 Ti SUPER)
   can OOM at full resolution with INT8. Prefer **GGUF Q4_K_M or Q3_K_M**, lower
   resolution, and fewer frames. Run exactly one 5-second test clip first and
   confirm it fits before batching.
4. **License:** the weights are a Model Derivative of MiniMax-H3 and are governed
   by the **MiniMax H3 Community License**. Use in the **European Union, United
   Kingdom, South Korea, and the United States requires authorization from
   MiniMax**. Surface this notice in the provider menu before any local
   generation — do not bury it in a log.
5. **Workflow format:** submit API-format JSON only. A UI-format workflow from the
   node pack's `workflows/` folder must be converted (or replaced by the bundled
   API templates) before execution.

## Quality notes

- Distillation changes the prompt response compared with the 20-step base model.
  Keep prompts concrete and shot-like; HyperFlow amplifies whatever motion and
  camera language the prompt implies.
- 4 steps is the fastest draft setting, 6 is the practical default, 8 is the
  quality pass. Use 6 for drafts and 8 for the take you intend to keep.
- CFG is fixed at **1.0** for the distilled schedule; raising it pushes the
  sampler off the distilled trajectory and degrades output.
- Prompt structure, audio direction, and reference-label conventions for
  MiniMax-H3 carry over unchanged. Read the `h3-prompt-writing` skill before
  composing t2v/i2v/flf2v/ref2v prompts.
- Reference images that disagree in lighting or scale produce identity drift.
  Keep both references consistent, and state in the prompt which is subject and
  which is setting.

## Provenance

- Distilled weights: Video Rebirth, distributed through
  `VideoRebirthAI/hyperflow-h3-flash` on ModelScope.
- Base model, text encoder, and VAEs: `Comfy-Org/MiniMax-H3`.
- Community INT8 workflows adapted from
  `BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI`.
- License: `MiniMax H3 Community License` (Model Derivative terms; territorial
  restrictions as above). OpenMontage bundles workflow JSON for convenience and
  does not relicense the weights.
