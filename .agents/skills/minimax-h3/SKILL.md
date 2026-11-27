---
name: minimax-h3
description: |
  Generate MiniMax H3 (Hailuo 3.0) video through the official MiniMax v2 API, fal.ai, Runway, ComfyUI Partner Nodes, or local open weights in ComfyUI. Use for 4-15 second 2K clips, first/last-frame animation, and image/video/audio reference-conditioned video.
---

# MiniMax H3

MiniMax H3 is the Hailuo 3.0 family. The first-party API identifier is
`MiniMax-H3`; fal.ai exposes the family as `hailuo-03`, and Runway uses
`hailuo3`. Do not substitute one provider's identifier into another API.

## Choose a route

| Route | Tool call | Execution |
|-------|-----------|-----------|
| MiniMax direct | `minimax_video`, `model: "MiniMax-H3"` | Hosted first-party v2 API; global or mainland-China region |
| fal.ai | `minimax_fal_video` | Hosted gateway; T2V, I2V, reference-to-video |
| Runway | `runway_video`, `model: "hailuo3"` | Hosted; 768P or 2K, 5–15 seconds |
| ComfyUI Partner Node | `comfyui_video`, `model_family: "minimax_h3_api"` | Hosted and billed in Comfy credits |
| ComfyUI open weights | `comfyui_video`, `model_family: "minimax_h3_local"` | Local GPU with official workflow and model stack |

For local ComfyUI, export the official workflow in API format and pass
`workflow_json` or `workflow_path` plus `output_node`. OpenMontage reports the
required diffusion model, Qwen3-VL text encoder, video VAE, and audio VAE; it
does not silently download large weights.

The ComfyUI host may be another machine. Server reachability does not establish
that the H3 model stack or a particular graph is ready. Bind inputs explicitly
as described by the `comfyui` skill, and check the chosen graph's supported
reference inputs rather than assuming that arbitrary multi-reference or
first/last-frame graphs are available locally.

## Project-scoped RefMods

For approved reusable character/state, location, and prop assets in the
narrative Cinematic pipeline, local H3 uses project-scoped RefMods by default.
Only enter this path after both the asset-sheet and local model-selection gates
are approved, and only for `reference_to_video` / Ref2VA shots. Existing
projects with approved asset takes and no explicit `project_refmod` opt-in keep
their current native route. An FL2VA-only project performs no RefMod extraction.
Extract each approved asset/state with `comfyui_refmod`, keep its
project copy and loader mapping in `NarrativeAssets`, then pass only the shot's
current `catalog.refmods_for_shot(shot_id)` rows to `comfyui_video` as
`refmod_assets`. New character records carry five standalone views in this
order: shoulder-up front, shoulder-up side, front full-body without head, side
full-body without head, and back full-body with head. Extract all five in one
`image_refs="separate"` bundle with `mode="Full Reference"`,
`extraction_preset="identity_encode"`, `ref_resolution=1024`, and
`max_tokens=0`; set `budget_policy="error"` and verify all five members before
registration. Locations, props, and legacy single-image assets continue to use
one `reference_path`. Use every row's `prompt_labels` and
descriptor in the prompt in the same order as the Text Encode reference map.
Picture numbers are assigned across the active bundle members, so a five-view
character contributes five labels and later assets start after them. Visual
RefMods use the node's numbered `<Picture N>` labels; do not substitute a
free-form `<Subject N>` token.

RefMods apply only to local H3 `reference_to_video` / Ref2VA graphs. They may be
used without native still images. The installed Text Encode node does not accept
separate native video references; for a mixed shot, preserve the motion
reference through native Ref2VA or ask the user to prioritize the Mod. Never
silently drop either reference or claim an unsupported combined map. Never send
local RefMods to hosted H3 or other provider routes. Exact
`first_last_frame_to_video` is FL2VA and cannot receive RefMods; if a shot
requires both, stop and ask which approved behavior to keep. A stale source or
Mod blocks the batch until that asset/state is
re-extracted. Use one explicit `server_url` for the H3 readiness menu,
extraction, and generation; pass the selected ComfyUI `workspace.path` to
extraction and block when that workspace is not local/shared. If live
`server_info` says the server is stopped or has no URL, block local H3 until it
is running; use a configured URL only when the `server_info` tool itself is
unavailable and the target's `object_info` validates the required nodes.

## Operations and prompting

- Text-to-video: concrete ratio; do not use `adaptive` without visual input.
- Image-to-video: provide a first frame.
- First/last-frame: provide both images and describe the motion between them.
- Reference-to-video: images, videos, and audio can be combined. Audio needs at
  least one visual reference.

Write prompts as subject + action + camera path + environment + lighting +
audio intent. MiniMax responds well to explicit camera direction. Keep the
requested motion achievable within 4–15 seconds and inspect native audio as
carefully as the image track.

## Provider differences

The direct MiniMax v2 route currently outputs 2K and supports 4–15 seconds.
Runway's Hailuo 3.0 route supports 768P/2K and documents 5–15 seconds. Partner
Nodes require network access and credits. Only the open-weight ComfyUI route is
local/offline after all models are installed.
