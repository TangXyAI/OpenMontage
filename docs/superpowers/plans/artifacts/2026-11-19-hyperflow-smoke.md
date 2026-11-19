# HyperFlow H3 Local Smoke Test — 2026-11-19

Local ComfyUI + HyperFlow INT8 text-to-video smoke test for the Hell-Grind
integration (Task 13, Steps 3-6). Purpose: prove the local MiniMax H3 route is
usable before recording it as the selected video route.

## Environment

- ComfyUI 0.45.0 at `G:/ComfyUI/Installs/ComfyUI/ComfyUI`
- Started with `comfy launch --background` (pid 37724, `http://127.0.0.1:8188`)
- GPU: NVIDIA GeForce RTX 4070 Ti SUPER, 16,376 MiB
- Readiness (`check_hyperflow_readiness(..., server_running=True)`): `ready: True`, no blockers, no warnings

## Exact command

```bash
.venv/Scripts/python.exe - <<'PY'
import json, time
from tools.video.comfyui_video import ComfyUIVideo
t0 = time.time()
r = ComfyUIVideo().execute({
    "prompt": "A rain-soaked neo-noir alley, one continuous shot, slow push-in.",
    "model_family": "minimax_h3_hyperflow_local",
    "checkpoint_name": "minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors",
    "loader": "auto",
    "operation": "text_to_video",
    "width": 960, "height": 544, "num_frames": 73, "steps": 6,
    "output_path": "projects/hyperflow-smoke/assets/video/t2v.mp4",
})
print("SUCCESS", r.success)
print("ERROR", r.error)
print("DATA", json.dumps(r.data, indent=2, default=str))
print("WALL_SECONDS", round(time.time() - t0, 2))
PY
```

## Result

- `success`: `True`; `error`: `None`
- Checkpoint: `minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors` (15 GB, INT8 convrot)
- Loader class selected by `loader: "auto"`: `HyperFlowLoader` (official INT8 path)
- Bundled workflow: `hyperflow_int8_t2v_api.json` (sha256 `3d22235779806c5d0d17bcd6a1e326affda8a19677a03eca7c5bd1cad6ba1c0c`)
- Output: `projects/hyperflow-smoke/assets/video/t2v.mp4` (817,637 bytes, non-zero)
- Requested: 960x544, 73 frames, 6 steps

## ffprobe

```text
streams:
  #0 video: h264, 960x544, 24/1 fps, 73 frames, 3.041667 s, 2,006,360 b/s
  #1 audio: aac, 32000 Hz, 2 channels, 3.042000 s, 128,075 b/s
format: mp4, duration 3.042000 s, size 817,637 bytes, 2,150,261 b/s
```

One video stream and one audio stream, as required. Duration is 3.042 s, not
~5 s: the bundled `CreateVideo` node renders at 24 fps (73 / 24 = 3.04 s),
while the tool reports `duration_seconds = num_frames / 16` (4.56 s). See
Concerns.

## Timing

Tool `data["timing"]`:

| Field | Value |
|---|---|
| prompt_id | `775fcd20-cbc9-4a77-b513-8fe7d044a3a8` |
| submit_s | 2.093 |
| client_queue_and_poll_s | 74.318 |
| comfy_prompt_exec_s | 68.37 |
| download_s | 2.104 |
| client_overhead_s | 10.188 |
| wall_s | 78.558 |

Outer wall clock (model load through file written): 81.25 s. ComfyUI log:
`Prompt executed in 68.37 seconds`; sampling 6/6 steps in 24 s after a 12 s
model initialization.

## Peak VRAM

ComfyUI's log does not print a peak VRAM figure. Sampled with `nvidia-smi`
during sampling: 15,420 MiB used of 16,376 MiB (baseline before the run:
1,155 MiB). This is the highest observed sample, not a continuous peak. The
run did not OOM; the fallback resolution (640x352, 49 frames) was not needed.

## Decision log

- Path: `projects/hyperflow-smoke/decision_log.json` (project workspace, gitignored)
- Entry `d-001`: stage `assets`, category `provider_selection`, subject
  `Video model and route`, selected `hyperflow_int8`, reason
  "Local smoke test passed at 960x544, 73 frames, 6 steps."

## Concerns

1. Output duration is 3.04 s at the bundled 24 fps rather than the
   ~4.56 s (num_frames/16) the tool reports. Parameter `num_frames=73` was kept
   as specified; a true 5 s clip would need `num_frames=121` at 24 fps, which
   conflicts with the tool's documented 16 fps assumption and should be fixed
   in product code, not in this smoke run.
2. VRAM headroom is thin: ~956 MiB free at the observed peak on a 16 GB card.
   Larger frame counts or resolutions are likely to OOM.
3. `workflow_provenance.model_stack` from the bundled workflow still lists the
   GGUF filenames; the executed `checkpoint_name` and `loader` fields confirm
   the INT8 checkpoint that actually ran.
