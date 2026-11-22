# Narrative Consistency — Asset-First Cinematic Production

> Sources: Hell-Grind CINEDANCE V4 (`.agents/skills/cinedance/SKILL.md`),
> ACTING SYSTEM (`.agents/skills/acting-system/SKILL.md`), LIRA image prompting
> (`.agents/skills/lira-image-prompts/SKILL.md`), and `docs/hell-grind-integration.md`
> sections 3 and 6.

Use this skill in the `cinematic` pipeline whenever a film has recurring characters,
locations, or props. Identity drift is almost never a prompt problem — it is an
**asset problem**. Lock the assets first, then generate shots against them. A shot that
drifts goes back to asset design, not back to the video model.

Read this before `assets` work; pair it with `skills/creative/video-model-selection.md`
for the model/route gate that follows asset lock.

## Asset order

Build and approve assets in this order. Do not start shot generation until every item
in the chain is locked.

1. **Descriptor text + reference image.** Write a short, stable descriptor for each
   character, location, and prop, then generate a reference image from it with
   `lira-image-prompts`. The descriptor is the contract; the image proves it.
2. **Character sheet** — a three-panel sheet per character:
   - face close-up,
   - **front full-body without head** (body, wardrobe, and proportions only; the head is
     deliberately omitted so the sheet cannot duplicate or contaminate the face),
   - back full-body.
3. **Location plate** — a clean empty plate of every location, shot from the master
   angle, before any character enters it.
4. **Prop sheet** — every recurring hero prop gets its own reference, scale, and
   material notes.
5. **Stress test** — run the asset set through the checks in "Stress test" below
   **before locking** the sheet. Done means approved for batch, not merely generated.

Record every approved asset under `assets/references/{characters,locations,props}/`
and link only shot-relevant references in `narrative_assets.json`. The exported
`asset_manifest.json` includes those linked references and the selected take;
unselected takes and unlinked reference sheets stay in the catalog.

## Character sheets

A character sheet is a texture-and-identity document, not one flattering portrait.

- Generate **separate texture references** for hair, skin, background, and fabric.
  One all-in-one image averages the details and loses the extremes (flyaway hair,
  skin pores, weave, grain).
- Keep the **descriptor word-for-word in every shot prompt**. Paraphrasing — even
  synonyms — is how identity drifts: the model follows the words it is given. Copy the
  approved descriptor verbatim, then add the scene-specific action and framing.
- Use the same seed and reference set for a character across the film where the
  provider exposes a seed. Re-state the descriptor even when a reference image is
  attached; reference tags alone are not an identity guarantee.

## Scene lock

Each location gets a locked spatial and lighting contract, established before any
performance is generated.

- **Empty plate first.** Generate the location with no characters, from the master
  angle. It becomes the ground truth for everything shot in that location.
- **Anchor objects.** Name and fix the landmarks that define the space (door, window,
  table, skyline) so blocking notes can reference them unambiguously.
- **One light source and one shadow direction.** State both explicitly, once, and keep
  them identical across every shot in the scene. Mixed shadow directions are the
  fastest way to make two shots read as different places.
- **First second is a wordless wide shot.** Open with a wide, character-free (or
  character-neutral) establishing beat. It grounds the viewer and gives the model a
  clean spatial reference before performance begins.
- **Optional 360° empty-scene sweep.** For reverse angles / shot-reverse-shot
  coverage, generate a slow sweep of the empty scene to fill in the off-camera space
  and reduce drift when the camera crosses the axis.

## Continuity contract

Strict continuity is enabled when the approved proposal records
`metadata.continuity_contract_version: "1.0"`. A missing marker means legacy
mode; do not retrofit already approved shots when an existing project opts in.

- `scene_plan.metadata.continuity_scene_ids` names the scenes governed by v1;
  new strict projects list every planned scene, while existing opted-in projects
  list only newly planned/replanned scenes. The `scene_continuity` keys must
  match that list; already approved legacy scenes remain unmarked. Start each
  strict scene's readable `location_map` summary with its stable `location_id`.
  The typed scene record holds the master angle, camera axis, anchors, and light.
- At shot-spec authoring, register each shot with both `shot_id` and `scene_id`.
  Use a shared `entity_id` for state variants of one recurring character or prop
  (for example, `hero-dry` and `hero-wet` both use `entity_id="hero"`). A
  location plate is a `location` asset whose state is `master_plate`.
- Track an entity's last known state across intervening shots where it is absent
  and across scene boundaries. Location geometry and lighting use the current
  scene contract; character and prop state carries forward unless an explicit
  change or reset is recorded.
- Before reference-sheet/plate generation, validate the planned scene contract.
  After the `asset_sheets` approval and shot-spec authoring, validate linked
  assets, references, file paths, and state transitions before compiling prompts
  or generating video shots.
- Build prompt context from the approved descriptor copied verbatim and only the
  linked references for that shot. Label each reference by role (`identity`,
  `location`, or `prop`) before passing the context to the selected provider's
  prompt workflow.
- Record every candidate take's review against the evidence frames and current
  media path. Each dimension is `pass`, `intentional_change`, `drift`, or
  `unclear`. Record `drift` and `unclear` candidates without an override for the
  audit trail, but only select them with an explicit user override reason;
  `NarrativeAssets.select_take` enforces this. Review the enhanced output again
  after enhancement changes the selected media.

## Stress test

Before locking any asset, test it against all four bars:

| Bar | Question |
|---|---|
| **Identity** | Does the face/character survive a new pose, angle, and light? |
| **Wardrobe** | Do fabric, color, and construction stay constant? |
| **Spatial readability** | Can a reviewer place the character and anchors in the scene from the asset alone? |
| **Reusability** | Will this still work for every planned shot, or was it overfit to one frame? |

Failure returns to **asset design** — rewrite the descriptor, regenerate the sheet or
plate, retest. Do **not** try to fix an asset failure by generating more takes; the
model is not the source of the inconsistency.

## Take budget

Generation is the expensive step, so budget it deliberately.

- **2–4 takes per shot.** Enough for a usable alternative, not enough to hide a weak
  prompt. If none of the takes lands, revisit the shot spec or the asset — do not
  extend the budget silently.
- **Draft at lower resolution.** Local drafts (HyperFlow / H3 local, or a low-resolution
  in-family route) are cheap and fast. Promote to final only after the take is chosen.
- **A family or route change needs a logged decision.** Moving between local and cloud,
  or between model families (H3 → Seedance 2.5, etc.), is never silent. Record it in
  `decision_log` under the existing `provider_selection` / `Video model and route`
  entry and get approval first. See `skills/creative/video-model-selection.md`.
- Present takes to the human for selection at the `assets` gate (`A8`) before exporting
  the chosen take to `asset_manifest.json`.
