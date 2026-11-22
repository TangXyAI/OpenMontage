# Reusable assets and shot takes

The cinematic pipeline can store a film's reference assets and takes in
`projects/<project-id>/artifacts/narrative_assets.json`. The agent still
authors the script and scene plan, reviews each candidate with the user, and
uses the normal asset and edit checkpoints. The catalog records decisions; it
does not automatically approve assets or choose takes.

## Store and select

All media paths must exist inside the project directory. Each distinct state
of a character, location or prop should have its own asset ID; state variants
share an `entity_id`. Keep `shot_id` distinct from `scene_id` and register the
shot-to-scene relationship explicitly. Strict continuity applies when the
approved proposal has `metadata.continuity_contract_version: "1.0"`;
`scene_plan.metadata.continuity_scene_ids` names the scenes under that contract.
For an existing project opt-in, previously approved scenes stay unmarked.

```python
from lib.narrative_assets import NarrativeAssets

catalog = NarrativeAssets("projects/my-film")
catalog.put_asset("hero-wet", "character", "Hero in raincoat, wet",
                  "assets/images/hero-wet.png", state="wet", entity_id="hero",
                  metadata={"source_tool": "comfyui_image"})
catalog.put_asset("loc-workshop-master", "location", "Empty workshop master plate",
                  "assets/references/locations/workshop.png", state="master_plate",
                  entity_id="loc-workshop")
catalog.register_shot("s01-sh01", "s01", continuity_contract_version="1.0")
catalog.link_assets("s01-sh01", ["hero-wet", "loc-workshop-master"])
catalog.add_take("s01-sh01", "take-01", "assets/video/s01-sh01-take-01.mp4",
                 5.0, {"source_tool": "comfyui_video", "seed": 42,
                       "prompt": "...", "model": "MiniMax-H3",
                       "workflow_provenance": {"workflow_hash_sha256": "..."}})
catalog.record_continuity_review("s01-sh01", "take-01", {
    "dimensions": {
        "identity_wardrobe": "pass", "location_anchors": "pass",
        "camera_continuity": "pass", "light_and_look": "pass", "story_state": "pass",
    },
    "notes": {
        "identity_wardrobe": "Identity and coat match.", "location_anchors": "Bench and doorway match.",
        "camera_continuity": "Screen direction and gaze match.", "light_and_look": "Window key stays camera-left.",
        "story_state": "The key remains in the right hand.",
    },
    "evidence_paths": ["assets/reviews/s01-sh01-frame.png"],
})  # after reviewing the candidate frames
catalog.select_take("s01-sh01", "take-01")  # after user review
manifest = catalog.asset_manifest()
edit = catalog.edit_decisions(["s01-sh01"], "ffmpeg")  # use the approved runtime
```

For strict shots, call `register_shot` with the scene ID and version, then use
`record_continuity_review(shot_id, take_id, review)` for each reviewed candidate.
The review records all five dimensions, short notes, and project-relative frame
evidence. `drift` or `unclear` can be recorded for a rejected candidate; an
override reason is required to select that take.
The manifest exports `scene_id` separately from `shot_id`; an enhancement that
changes the selected media path requires a fresh review of the enhanced file.

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
Use a unique file path for every take and do not overwrite files already
registered in the catalog. A process crash can leave `narrative_assets.lock`;
after confirming no writer is active, remove that file before retrying.

## Remote ComfyUI

Configure `COMFYUI_SERVER_URL`, or the image/video-specific overrides, to point
to the machine running ComfyUI. Install the models and API-format workflows on
that machine. A custom workflow is not automatically rewritten: use explicit
`workflow_bindings` as described in the ComfyUI skill, including a binding for
the local reference image when an image-conditioned graph supports one. The
image is uploaded to the remote server. MiniMax H3 local requires its own model
stack and workflow; ComfyUI Partner Nodes are hosted services. Local H3 mode
rejects known hosted partner nodes, but arbitrary third-party nodes must be
inspected separately before claiming an entirely offline workflow.

For a custom graph, `workflow_provenance.input_bindings` records which requested
parameters were actually injected; `requested_parameters_applied` is false
when a supplied prompt, seed, dimensions, or reference was not bound. The
historical top-level prompt/seed describe the request and are not proof that
an unbound graph used them.

If an image or video job times out, save `result.data["prompt_id"]` and
`result.data["resume_context"]`. Call the same ComfyUI tool again with these as
`resume_prompt_id` and `resume_context`; the existing job is polled without
another upload or submission. Without the original context, resumed task
provenance is explicitly unknown. Provider availability alone does not confirm
that a particular H3 workflow or model stack is ready. Test a reference image,
an H3 shot and a composition on the target machine before claiming real-model
end-to-end support.
