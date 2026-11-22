"""Validation and model-neutral prompt context for narrative shot continuity."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal


class ContinuityValidationError(ValueError):
    """Raised when strict narrative continuity inputs are incomplete or inconsistent."""

    def __init__(self, issues: list[str] | tuple[str, ...]):
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


def continuity_mode(proposal_packet: Mapping[str, Any]) -> Literal["legacy", "strict"]:
    """Resolve the continuity contract version recorded in a proposal packet."""
    if not isinstance(proposal_packet, Mapping):
        raise ContinuityValidationError(["proposal_packet must be an object"])
    metadata = proposal_packet.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ContinuityValidationError(["proposal_packet.metadata must be an object"])
    if "continuity_contract_version" not in metadata:
        return "legacy"
    version = metadata["continuity_contract_version"]
    if version == "1.0":
        return "strict"
    raise ContinuityValidationError([f"unsupported continuity contract version: {version!r}"])


def validate_scene_plan_continuity(scene_plan: Mapping[str, Any], *, strict: bool) -> None:
    """Validate the typed location contract before reference-sheet generation."""
    if not strict:
        return
    if not isinstance(scene_plan, Mapping):
        raise ContinuityValidationError(["scene_plan must be an object"])

    issues: list[str] = []
    scenes = scene_plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ContinuityValidationError(["scene_plan.scenes must be a non-empty array"])

    scene_ids: list[str] = []
    for index, scene in enumerate(scenes):
        scene_id = scene.get("id") if isinstance(scene, Mapping) else None
        if not isinstance(scene_id, str) or not scene_id.strip():
            issues.append(f"scene_plan.scenes[{index}] is missing a scene id")
        elif scene_id in scene_ids:
            issues.append(f"scene_plan contains duplicate scene_id {scene_id}")
        else:
            scene_ids.append(scene_id)
    if issues:
        raise ContinuityValidationError(issues)

    metadata = scene_plan.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ContinuityValidationError(["scene_plan.metadata must be an object"])
    location_maps = metadata.get("location_map")
    scene_contracts = metadata.get("scene_continuity")
    strict_scene_ids = metadata.get("continuity_scene_ids")
    if not isinstance(location_maps, Mapping):
        raise ContinuityValidationError(["scene_plan.metadata.location_map is required in strict mode"])
    if not isinstance(scene_contracts, Mapping):
        raise ContinuityValidationError(["scene_plan.metadata.scene_continuity is required in strict mode"])
    if not isinstance(strict_scene_ids, list) or not strict_scene_ids:
        raise ContinuityValidationError(["scene_plan.metadata.continuity_scene_ids must name strict scenes"])

    invalid_scene_ids = [item for item in strict_scene_ids if not isinstance(item, str) or not item.strip()]
    if invalid_scene_ids:
        raise ContinuityValidationError(["continuity_scene_ids contains an empty or invalid scene id"])
    if len(strict_scene_ids) != len(set(strict_scene_ids)):
        raise ContinuityValidationError(["continuity_scene_ids contains duplicate scene ids"])

    strict_ids = set(strict_scene_ids)
    known_ids = set(scene_ids)
    unknown_strict_ids = sorted(strict_ids - known_ids)
    if unknown_strict_ids:
        issues.append(f"continuity_scene_ids has unknown scene ids: {', '.join(unknown_strict_ids)}")
    invalid_location_keys = [key for key in location_maps if not isinstance(key, str)]
    invalid_contract_keys = [key for key in scene_contracts if not isinstance(key, str)]
    if invalid_location_keys:
        issues.append("scene_plan.metadata.location_map keys must be scene id strings")
    if invalid_contract_keys:
        issues.append("scene_plan.metadata.scene_continuity keys must be scene id strings")
    location_keys = {key for key in location_maps if isinstance(key, str)}
    contract_keys = {key for key in scene_contracts if isinstance(key, str)}
    missing_summaries = sorted(strict_ids - location_keys)
    extra_summaries = sorted(location_keys - known_ids)
    if missing_summaries:
        issues.append(f"scene_plan.metadata.location_map is missing strict scene ids: {', '.join(missing_summaries)}")
    if extra_summaries:
        issues.append(f"scene_plan.metadata.location_map has unknown scene ids: {', '.join(extra_summaries)}")
    missing_contracts = sorted(strict_ids - contract_keys)
    extra_contracts = sorted(contract_keys - strict_ids)
    if missing_contracts:
        issues.append(f"scene_plan.metadata.scene_continuity is missing scene ids: {', '.join(missing_contracts)}")
    if extra_contracts:
        issues.append(f"scene_plan.metadata.scene_continuity has unmarked scene ids: {', '.join(extra_contracts)}")

    for scene_id in strict_scene_ids:
        summary = location_maps.get(scene_id)
        if not isinstance(summary, str) or not summary.strip():
            issues.append(f"scene {scene_id} needs a non-empty location_map summary")
            continue
        contract = scene_contracts.get(scene_id)
        if not isinstance(contract, Mapping):
            issues.append(f"scene {scene_id} needs a typed scene_continuity contract")
            continue

        location_id = contract.get("location_id")
        if not isinstance(location_id, str) or not location_id.strip():
            issues.append(f"scene {scene_id} needs a location_id")
        elif location_id not in summary:
            issues.append(f"scene {scene_id} location_map summary must identify {location_id}")

        for name in ("master_angle", "camera_axis"):
            if not isinstance(contract.get(name), str) or not contract[name].strip():
                issues.append(f"scene {scene_id} needs {name}")

        anchors = contract.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            issues.append(f"scene {scene_id} needs at least one spatial anchor")
        else:
            for anchor in anchors:
                if (not isinstance(anchor, Mapping)
                        or not isinstance(anchor.get("id"), str) or not anchor["id"].strip()
                        or not isinstance(anchor.get("position"), str) or not anchor["position"].strip()):
                    issues.append(f"scene {scene_id} has an invalid spatial anchor")
                    break

        lighting = contract.get("lighting")
        if not isinstance(lighting, Mapping):
            issues.append(f"scene {scene_id} needs a lighting contract")
        else:
            missing_lighting = [key for key in ("key_source", "direction", "shadow_direction")
                                if not isinstance(lighting.get(key), str) or not lighting[key].strip()]
            if missing_lighting:
                issues.append(f"scene {scene_id} lighting is missing: {', '.join(missing_lighting)}")

    if issues:
        raise ContinuityValidationError(issues)


def _resolve_project_file(project_root: Path, path: Any) -> Path | None:
    if not isinstance(path, (str, Path)) or not str(path).strip():
        return None
    candidate = Path(path)
    full = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
    if not full.is_relative_to(project_root) or not full.is_file():
        return None
    return full


def _asset_entity_id(asset_id: str, asset: Mapping[str, Any]) -> str:
    return str(asset.get("entity_id") or asset_id)


def validate_shot_continuity(
    scene_plan: Mapping[str, Any],
    shot_specs: Mapping[str, Any],
    catalog_data: Mapping[str, Any],
    project_root: str | Path,
    *,
    strict: bool,
) -> None:
    """Validate strict shot contracts, linked references, and carried entity states."""
    if not strict:
        return
    validate_scene_plan_continuity(scene_plan, strict=True)

    root = Path(project_root).resolve()
    issues: list[str] = []
    scene_contracts = scene_plan["metadata"]["scene_continuity"]
    location_maps = scene_plan["metadata"]["location_map"]
    scene_ids = {scene["id"] for scene in scene_plan["scenes"]}
    strict_scene_ids = set(scene_plan["metadata"]["continuity_scene_ids"])
    if not isinstance(shot_specs, Mapping) or not isinstance(shot_specs.get("shots"), list) or not shot_specs["shots"]:
        raise ContinuityValidationError(["shot_specs.shots must be a non-empty array"])
    if not isinstance(catalog_data, Mapping) or not isinstance(catalog_data.get("assets"), Mapping) or not isinstance(catalog_data.get("shots"), Mapping):
        raise ContinuityValidationError(["narrative asset catalog must contain assets and shots objects"])

    catalog_assets = catalog_data["assets"]
    catalog_shots = catalog_data["shots"]
    positions: dict[str, int] = {}
    for index, shot in enumerate(shot_specs["shots"]):
        if not isinstance(shot, Mapping):
            issues.append(f"shot_specs.shots[{index}] must be an object")
            continue
        shot_id = shot.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id.strip():
            issues.append(f"shot_specs.shots[{index}] is missing shot_id")
            continue
        if shot_id in positions:
            issues.append(f"duplicate shot_id {shot_id}")
        else:
            positions[shot_id] = index

    last_states: dict[str, tuple[str, str]] = {}
    for index, shot in enumerate(shot_specs["shots"]):
        if not isinstance(shot, Mapping):
            continue
        shot_id = shot.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id.strip():
            continue
        scene_id = shot.get("scene_id")
        if scene_id not in scene_ids:
            issues.append(f"shot {shot_id} has unknown scene_id {scene_id!r}")
            continue
        catalog_shot = catalog_shots.get(shot_id)
        continuity = shot.get("continuity")
        if scene_id not in strict_scene_ids:
            marked_in_spec = isinstance(continuity, Mapping) and continuity.get("contract_version") == "1.0"
            marked_in_catalog = isinstance(catalog_shot, Mapping) and catalog_shot.get("continuity_contract_version") == "1.0"
            if marked_in_spec or marked_in_catalog:
                issues.append(f"shot {shot_id} is strict but scene {scene_id} is not in continuity_scene_ids")
            last_states.clear()
            continue
        scene_contract = scene_contracts[scene_id]
        if not isinstance(continuity, Mapping) or continuity.get("contract_version") != "1.0":
            issues.append(f"shot {shot_id} is missing continuity contract version 1.0")
            continue

        previous_shot_id = continuity.get("previous_shot_id")
        if previous_shot_id is not None and (previous_shot_id not in positions or positions[previous_shot_id] >= index):
            issues.append(f"shot {shot_id} has invalid previous_shot_id {previous_shot_id!r}")

        location_id = scene_contract["location_id"]
        if continuity.get("location_id") != location_id:
            issues.append(f"shot {shot_id} location_id does not match scene {scene_id}")
        if shot.get("location_map") != location_maps.get(scene_id):
            issues.append(f"shot {shot_id} location_map does not match scene {scene_id}")

        if not isinstance(catalog_shot, Mapping):
            issues.append(f"shot {shot_id} is not registered in NarrativeAssets")
            linked_asset_ids: set[str] = set()
        else:
            if catalog_shot.get("scene_id") != scene_id:
                issues.append(f"shot {shot_id} catalog scene_id does not match {scene_id}")
            if catalog_shot.get("continuity_contract_version") != "1.0":
                issues.append(f"shot {shot_id} catalog is missing continuity contract version 1.0")
            raw_asset_ids = catalog_shot.get("asset_ids", [])
            linked_asset_ids = set(raw_asset_ids) if isinstance(raw_asset_ids, list) else set()

        references = shot.get("references")
        if not isinstance(references, list):
            issues.append(f"shot {shot_id} references must be an array")
            references = []
        resolved_references: list[tuple[Mapping[str, Any], Mapping[str, Any], Path]] = []
        for reference in references:
            if not isinstance(reference, Mapping):
                issues.append(f"shot {shot_id} has an invalid reference record")
                continue
            asset_id = reference.get("asset_id")
            role = reference.get("role")
            asset = catalog_assets.get(asset_id) if isinstance(asset_id, str) else None
            if not isinstance(asset, Mapping):
                issues.append(f"shot {shot_id} references unknown asset_id {asset_id!r}")
                continue
            if asset_id not in linked_asset_ids:
                issues.append(f"shot {shot_id} reference {asset_id} is not linked in NarrativeAssets")
            reference_path = _resolve_project_file(root, reference.get("path"))
            asset_path = _resolve_project_file(root, asset.get("path"))
            if reference_path is None or asset_path is None:
                issues.append(f"shot {shot_id} reference path is missing or outside the project for {asset_id}")
                continue
            if reference_path != asset_path:
                issues.append(f"shot {shot_id} reference path does not match catalog asset {asset_id}")
            if not isinstance(role, str) or not role.strip():
                issues.append(f"shot {shot_id} reference {asset_id} is missing a role")
            resolved_references.append((reference, asset, reference_path))

        location_reference_found = any(
            reference.get("role") == "location"
            and asset.get("kind") == "location"
            and _asset_entity_id(str(reference.get("asset_id")), asset) == location_id
            and asset.get("state") == "master_plate"
            for reference, asset, _ in resolved_references
        )
        if not location_reference_found:
            issues.append(f"shot {shot_id} is missing the approved master plate reference for {location_id}")

        entities = continuity.get("entities")
        if not isinstance(entities, list):
            issues.append(f"shot {shot_id} continuity.entities must be an array")
            entities = []
        seen_entity_ids: set[str] = set()
        for entity in entities:
            if not isinstance(entity, Mapping):
                issues.append(f"shot {shot_id} has an invalid entity state")
                continue
            entity_id = entity.get("entity_id")
            asset_id = entity.get("asset_id")
            state = entity.get("state")
            if not all(isinstance(value, str) and value.strip() for value in (entity_id, asset_id, state)):
                issues.append(f"shot {shot_id} has an entity state missing entity_id, asset_id, or state")
                continue
            if entity_id in seen_entity_ids:
                issues.append(f"shot {shot_id} has duplicate entity_id {entity_id}")
                continue
            seen_entity_ids.add(entity_id)
            asset = catalog_assets.get(asset_id)
            if not isinstance(asset, Mapping):
                issues.append(f"shot {shot_id} references unknown asset_id {asset_id}")
                continue
            if asset_id not in linked_asset_ids:
                issues.append(f"shot {shot_id} entity asset {asset_id} is not linked in NarrativeAssets")
            if _asset_entity_id(asset_id, asset) != entity_id or asset.get("state") != state:
                issues.append(f"shot {shot_id} entity {entity_id} state does not match catalog asset {asset_id}")
            expected_role = "identity" if asset.get("kind") == "character" else "prop" if asset.get("kind") == "prop" else None
            if expected_role is not None and not any(
                ref.get("asset_id") == asset_id and ref.get("role") == expected_role
                for ref, _, _ in resolved_references
            ):
                issues.append(f"shot {shot_id} entity {entity_id} is missing its {expected_role} reference")

            previous_state = last_states.get(entity_id)
            if previous_state is not None and previous_state[0] != state:
                changes = continuity.get("intentional_changes", [])
                declared = any(
                    isinstance(change, Mapping)
                    and change.get("entity_id") == entity_id
                    and change.get("from_state") == previous_state[0]
                    and change.get("to_state") == state
                    and isinstance(change.get("reason"), str)
                    and change["reason"].strip()
                    for change in changes
                ) if isinstance(changes, list) else False
                if not declared:
                    issues.append(
                        f"shot {shot_id} entity {entity_id} state changed from {previous_state[0]} to {state} "
                        "without a declared intentional_changes entry"
                    )
            last_states[entity_id] = (state, shot_id)

    if issues:
        raise ContinuityValidationError(issues)


def build_shot_context(
    shot: Mapping[str, Any],
    scene_contract: Mapping[str, Any],
    catalog_data: Mapping[str, Any],
    project_root: str | Path,
) -> dict[str, Any]:
    """Assemble approved descriptors and references without provider syntax."""
    root = Path(project_root).resolve()
    if not isinstance(shot, Mapping) or not isinstance(scene_contract, Mapping):
        raise ContinuityValidationError(["shot and scene contract must be objects"])
    if not isinstance(catalog_data, Mapping) or not isinstance(catalog_data.get("assets"), Mapping):
        raise ContinuityValidationError(["narrative asset catalog must contain an assets object"])
    assets = catalog_data["assets"]
    continuity = shot.get("continuity")
    if not isinstance(continuity, Mapping):
        raise ContinuityValidationError([f"shot {shot.get('shot_id', '<unknown>')} is missing continuity data"])

    references = []
    for reference in shot.get("references", []):
        if not isinstance(reference, Mapping):
            raise ContinuityValidationError(["shot contains an invalid reference record"])
        asset_id = reference.get("asset_id")
        asset = assets.get(asset_id) if isinstance(asset_id, str) else None
        path = _resolve_project_file(root, reference.get("path"))
        if not isinstance(asset, Mapping) or path is None:
            raise ContinuityValidationError([f"shot reference path or asset is unavailable for {asset_id!r}"])
        references.append({
            "asset_id": asset_id,
            "kind": reference.get("kind"),
            "role": reference.get("role"),
            "path": str(path),
        })

    stable_descriptors = []
    for entity in continuity.get("entities", []):
        asset_id = entity.get("asset_id") if isinstance(entity, Mapping) else None
        entity_asset = assets.get(asset_id) if isinstance(asset_id, str) else None
        if not isinstance(entity_asset, Mapping):
            raise ContinuityValidationError([f"shot entity references unknown asset_id {asset_id!r}"])
        stable_descriptors.append({
            "entity_id": entity.get("entity_id"),
            "asset_id": asset_id,
            "state": entity.get("state"),
            "text": entity_asset.get("description", ""),
        })

    location_fields = ("location_id", "master_angle", "camera_axis", "anchors", "lighting", "constants", "allowed_changes")
    location_lock = {key: scene_contract[key] for key in location_fields if key in scene_contract}
    return {
        "stable_descriptors": stable_descriptors,
        "references": references,
        "location_lock": location_lock,
        "carried_states": list(continuity.get("carried_states", [])),
        "intentional_changes": list(continuity.get("intentional_changes", [])),
        "shot_specific": {
            key: shot[key]
            for key in ("scene_context", "first_frame", "action_timing", "optics", "camera", "style", "constraints")
            if key in shot
        },
    }
