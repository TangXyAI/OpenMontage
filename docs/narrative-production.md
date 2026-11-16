# Reusable assets and shot takes

The cinematic pipeline can store a film's reference assets and takes in
`projects/<project-id>/artifacts/narrative_assets.json`. The agent still
authors the script and scene plan, reviews each candidate with the user, and
uses the normal asset and edit checkpoints. The catalog records decisions; it
does not automatically approve assets or choose takes.

## Store and select

All media paths must exist inside the project directory. Each distinct state
of a character, location or prop should have its own ID. Shot IDs should match
scene IDs in the scene plan.

```python
from lib.narrative_assets import NarrativeAssets

catalog = NarrativeAssets("projects/my-film")
catalog.put_asset("hero-wet", "character", "Hero in raincoat, wet",
                  "assets/images/hero-wet.png", state="wet",
                  metadata={"source_tool": "comfyui_image"})
catalog.link_assets("shot-01", ["hero-wet"])
catalog.add_take("shot-01", "take-01", "assets/video/shot-01-take-01.mp4",
                 5.0, {"source_tool": "comfyui_video", "seed": 42,
                       "prompt": "...", "model": "MiniMax-H3",
                       "workflow_provenance": {"workflow_hash_sha256": "..."}})
catalog.select_take("shot-01", "take-01")  # after user review
manifest = catalog.asset_manifest()
edit = catalog.edit_decisions(["shot-01"], "ffmpeg")  # use the approved runtime
```

Each mutation persists immediately. `asset_manifest()` exports the selected
takes and scene-linked reference images in the existing asset manifest schema;
the catalog retains all candidates and their full metadata. `edit_decisions`
returns cuts in the specified order, initially using each selected take in full.
The edit director must review the cuts and add audio and transitions as needed,
then write the canonical artifact and checkpoint. Pass `project_dir` to
`video_compose`. No unselected take is exported as a final cut. Changing a
selection requires a new approved assets checkpoint and a new edit checkpoint.
The catalog is single-writer: a stale instance must be reloaded before saving;
concurrent writers get an error rather than silently overwriting each other.

## Remote ComfyUI

Configure `COMFYUI_SERVER_URL`, or the image/video-specific overrides, to point
to the machine running ComfyUI. Install the models and API-format workflows on
that machine. A custom workflow is not automatically rewritten: use explicit
`workflow_bindings` as described in the ComfyUI skill, including a binding for
the local reference image when an image-conditioned graph supports one. The
image is uploaded to the remote server. MiniMax H3 local requires its own model
stack and workflow; ComfyUI Partner Nodes are hosted services.

If a video job times out, save `result.data["prompt_id"]` and
`result.data["resume_context"]`. Call `comfyui_video` again with these as
`resume_prompt_id` and `resume_context`; the existing job is polled without
another upload or submission. Without the original context, resumed task
provenance is explicitly unknown. Provider availability alone does not confirm
that a particular H3 workflow or model stack is ready. Test a reference image,
an H3 shot and a composition on the target machine before claiming real-model
end-to-end support.
