# Enhancement Pilot Report — 2026-11-21

Status: **pending**. This file is created ahead of the operational run so the
design and plan references resolve; Task 10 fills it with measured results.

Planned content:

- Environment: ComfyUI version, GPU, model roots, readiness result.
- SeedVR2 run: input take, resolution, batch/overlap, wall time, VRAM peak,
  output spec (short edge, fps, duration, audio streams), SSIM.
- FaceRefine run: source clip, reference images, prompt source, denoise,
  wall time, output spec, identity comparison.
- Pilot integration: `apply_enhancement` write-back, regenerated
  `edit_decisions`, raised `compose_target`, narrative-selection guard result.
- Final enhanced render: path, resolution, fps, duration, audio, file size.
- Known limitations: FaceRefine largest-face-only behavior, SeedVR2 time cost,
  multi-character shots, model-name portability.
