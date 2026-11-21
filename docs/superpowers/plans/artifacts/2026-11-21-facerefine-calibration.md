# FaceRefine Denoise Calibration — 2026-11-21

Calibration run for the local H3 FaceRefine route. This is **not** a pipeline
production run: it reuses the smoke clip and the experiment's two reference
images from `projects/_h3-api-export`, not an approved three-panel character
sheet. Its purpose is to replace the placeholder denoise guidance in
`.agents/skills/video-enhancement/SKILL.md`.

## Setup

- Tool: `tools/enhancement/comfyui_enhance.py`, `operation="face_refine"`.
- Source: `G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_face_source_07mp.mp4`
  (640×1136, 24 fps, 73 frames, 3.042 s).
- References: `smoke_ref_cui_zhu.png` (identity), `smoke_ref_cui_zhu_wardrobe.png`
  (wardrobe).
- Prompt: node `"2".inputs.value` of
  `projects/_h3-api-export/smoke_singularity_ref2v.api.json`.
- Seed 42, `face_select="largest_face"`, `identity_threshold=0.28`,
  `face_denoise_multiplier=1.0`.
- Each run preserved 640×1136, 24 fps, 3.042 s, one AAC stream.
- ComfyUI 0.45.0, RTX 4070 Ti SUPER 16 GB, local weights, $0.

## Results

| Denoise | SSIM vs source | Wall | Identity / pose judgement |
|---|---|---|---|
| 0.20 | 0.991187 | 205.5 s | Subtle sharpening; identity and head pose closest to the source. 0.6 s still looks down-left. |
| 0.30 | 0.990154 | 169.5 s | Clearly sharper; minor pose/identity shift. Best practical default for identity-sensitive faces. |
| 0.40 | 0.988728 | 169.4 s | Visibly sharper but the face reads as a similar different person (wider eyes, different nose/chin); head turns toward camera at clip start. |
| 0.50 | 0.987818 | 157.5 s | No sharpness gain over 0.40, more drift. Not recommended. |

Comparison sheets:

- Face crops (rows: source, 0.20, 0.30, 0.40, 0.50; columns: 0.6 s, 2.0 s):
  `projects/hyperflow-pilot/renders/_preview/facerefine-denoise-face-sheet.png`
- Full frames:
  `projects/hyperflow-pilot/renders/_preview/facerefine-denoise-sheet.png`

## Recommendation

- Identity-sensitive hero faces: **0.25–0.30**.
- Sharpness over identity, after comparing frames: 0.40 (current default).
- 0.50 has no measured advantage and is not recommended.
- The tool still cannot measure identity; a human frame comparison is required
  at the assets gate.

## Command shape

```python
ComfyUIEnhance().execute({
    "operation": "face_refine",
    "input_path": "G:/ComfyUI/Installs/ComfyUI/ComfyUI/input/smoke_face_source_07mp.mp4",
    "output_path": f"projects/hyperflow-pilot/assets/video/calibration/face-refine-denoise-{d:.2f}.mp4",
    "project_dir": "projects/hyperflow-pilot",
    "reference_image_paths": [ref_face, ref_wardrobe],
    "prompt": source_prompt,
    "denoise": d,
    "timeout_seconds": 1800,
})
```
