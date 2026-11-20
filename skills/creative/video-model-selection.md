# Video Model Selection — Local-First Route Gate

> Sources: `docs/hell-grind-integration.md` sections 4 and 6, the tool registry, and
> `.agents/skills/hyperflow-h3/SKILL.md`.

Use this skill in the `cinematic` pipeline (and any pipeline that generates video with
`video_selector` / a concrete video tool) to choose and confirm the **model family and
route before the first generation call**. The user selects; the agent never silently
re-routes. Pair it with `skills/creative/narrative-consistency.md` — assets lock first,
then this gate opens.

Readiness, model ids, and costs come from the registry at runtime (tool `status` and
`estimate_cost`). Never hardcode them here or in a prompt.

## Local first

Default preference order, cheapest and most private first:

```
HyperFlow GGUF → HyperFlow INT8 → H3 local → cloud H3 → Seedance 2.5 → Pika H3 Flex
```

- **HyperFlow GGUF** — local ComfyUI + MiniMax H3 with the Q4_K_M HyperFlow checkpoints.
  The safest fit for a 16 GB GPU; start here.
- **HyperFlow INT8** — local ComfyUI + HyperFlow INT8 checkpoints. Faster, but the full
  INT8 route can OOM on 16 GB; smoke-test one 5-second clip before batching.
- **H3 local** — local MiniMax H3 weights without HyperFlow (more steps, existing
  hybrid / Singularity weights).
- **Cloud H3** — MiniMax H3 via official / fal / Runway / Atlas / ComfyUI partner nodes.
- **Seedance 2.5** — fal / Ark / Atlas. Use when the brief needs a non-H3 texture or
  when local and cloud H3 cannot satisfy it.
- **Pika H3 Flex** — cheapest draft route, up to 4K upload, up to 12 references.

Local routes win whenever they produce an acceptable result. Leaving a local route for
cloud is a gated change (see below), not a fallback the agent may take on its own.

## Selection gate

Two explicit approvals, recorded in `decision_log` under the same
`category: provider_selection` / `subject: Video model and route`:

1. **proposal** — present the family × route shortlist (capability, limits, cost,
   recommendation). The user selects the **model family + preferred route + backup
   route**. Nothing is generated yet.
2. **assets, before the first generation (paid or local)** — confirm the exact batch parameters:
   **model id, resolution, duration, take count, and total cost**. Only after this
   confirmation does batch generation start.

An unavailable or unselected route means no generation. "The agent picked something"
is not a selection.

## Menu

Build the menu from live registry data:

- Read each candidate tool's `status` and `estimate_cost`; show availability and cost
  exactly as the registry reports them.
- **Show local routes first**, with readiness (weights / nodes / VAE / VRAM) and step
  count so the user can compare against cloud. A **HyperFlow** local route is
  available only when its quantization is ready **and** the ComfyUI tool/server is
  available; `h3_local` keeps the tool-status behavior. Show both blockers when
  either fails.
- **Show missing local files as blockers**, not silent omissions, with a download hint
  (for example the ModelScope file names and target directories from
  `.agents/skills/hyperflow-h3/SKILL.md`).
- Surface the HyperFlow weight license note (MiniMax H3 Community License; EU/UK/KR/US
  use requires MiniMax authorization) wherever a HyperFlow route appears.
- `video_selector` only discovers and preflights. Execution calls the **explicit tool
  and model id the user chose** — never let selector scoring swap the route unseen.

## Local H3 variants

When the brief is local-only, the route row is not the whole choice. Enumerate every
installed MiniMax H3 checkpoint and let the user pick one:

```python
from lib.local_h3_variants import (
    LOCAL_H3_DECISION_SUBJECT, build_local_h3_menu, render_local_h3_menu,
    variant_option, variant_route,
)

variants = build_local_h3_menu(model_roots, workflow_roots)
print(render_local_h3_menu(variants))
```

- List **every installed checkpoint**, including ones that cannot run yet. Show family,
  quantization, supported operations, size, the matching workflow, and
  `runnable`/`setup`.
- HyperFlow has bundled API workflows, so its `fl2va`/`ref2va` variants are runnable.
  Stock, hybrid, DaSiWa and Singularity variants are installed but their ComfyUI
  workflows are UI-only on this machine; show the export hint instead of hiding them.
- The user selects a `variant_id`. Map the menu rows with `variant_option` /
  `variant_route`, then record the choice under `provider_selection` /
  `Local H3 variant`:

  ```python
  from lib.video_model_selection import record_selection

  selected = next(row for row in variants if row["variant_id"] == chosen_id)
  record_selection(
      "projects/<project-id>/decision_log.json", "<project-id>", "proposal",
      variant_route(selected),
      [variant_option(row) for row in variants],
      "user selected a local H3 variant",
      subject=LOCAL_H3_DECISION_SUBJECT,
  )
  ```

  Only a `runnable` variant may proceed to take generation; a UI-only workflow must be
  exported to API format first. Never substitute HyperFlow for a different variant the
  user chose.

## Draft and final

Iterate cheaply without changing the look:

- **Lower resolution within the same family is allowed** — HyperFlow low-res/6-step
  draft → same weights at 8-step/high-res final; H3 Max 480P → 1080P; Pika 480p → 768p;
  Seedance 480p → 720p. Same family, same character of output, no extra approval.
- **A same-model route change is allowed but logged** — for example official H3 → Atlas
  H3. It is a route change, not a model change, but it still gets a new decision entry.
- **local → cloud, or cross-family draft → final, is a logged, approved change.** Ask
  first; the texture and grade can shift, so the user owns that choice. Append the new
  decision; keep the superseded route in `options_considered`.

## No silent fallback

If the selected route is unavailable — ComfyUI is down, weights are missing, the route
OOMs, or a provider key is unset — **stop the run**. Do not quietly substitute another
tool, family, or local/cloud direction, and do not downgrade to stills or an animatic.

Report the blocker with: what was attempted, what failed (auth vs. availability vs.
OOM vs. quality), the available options, and a recommendation. **Re-selection is
required** — the user picks the new family/route (or approves the retry after an
environment fix), and that choice is written as a new `decision_log` entry before
generation resumes.
