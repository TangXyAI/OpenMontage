"""Persistent reference assets and explicitly selected shot takes.

This module stores production facts; creative selection remains with the agent
and the user. Paths in the catalog are relative to the project root.
"""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote


def validate_character_sheet(descriptor: str, sheet_paths: Sequence[str | Path]) -> None:
    """Validate the three-image character sheet required before locking an asset.

    Hell-Grind requires a non-empty descriptor and exactly three reference
    images (face close-up, front full-body without head, back full-body). Only
    paths are checked; image contents are never read and no catalog state is
    touched.
    """
    if not descriptor or not descriptor.strip():
        raise ValueError("Character sheet needs a non-empty descriptor")
    paths = [Path(path) for path in sheet_paths]
    if len(paths) != 3:
        raise ValueError(f"Character sheet needs exactly three images, got {len(paths)}")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError("Character sheet is missing image files: " + ", ".join(missing))


class NarrativeAssets:
    def __init__(self, project_dir: str | Path):
        self.root = Path(project_dir).resolve()
        self.path = self.root / "artifacts" / "narrative_assets.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"version": "1.0", "assets": {}, "shots": {}}
        self._revision = self._current_revision()

    def _current_revision(self) -> str | None:
        return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None

    def _media(self, path: str) -> str:
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root) or not full.is_file():
            raise ValueError(f"Media must exist inside the project: {path}")
        return str(full.relative_to(self.root))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("Catalog is being changed by another writer") from exc
        try:
            if self._current_revision() != self._revision:
                raise RuntimeError("Catalog changed since it was read; reload before saving")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as file:
                temp = file.name
                try:
                    json.dump(self.data, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                except Exception:
                    os.unlink(temp)
                    raise
            try:
                os.replace(temp, self.path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            self._revision = self._current_revision()
        finally:
            os.close(descriptor)
            lock.unlink()

    def put_asset(self, asset_id: str, kind: str, description: str, path: str, *, state: str = "default", metadata: dict | None = None, entity_id: str | None = None) -> None:
        if not asset_id or kind not in {"character", "location", "prop"}:
            raise ValueError("Asset needs an id and kind character, location, or prop")
        if entity_id is not None and not entity_id.strip():
            raise ValueError("Asset entity id cannot be empty")
        if asset_id in self.data["assets"]:
            raise ValueError(f"Asset already exists: {asset_id}")
        self.data["assets"][asset_id] = {
            "kind": kind,
            "entity_id": entity_id if entity_id is not None else asset_id,
            "description": description,
            "path": self._media(path),
            "state": state,
            "metadata": metadata or {},
        }
        self._save()

    def register_shot(self, shot_id: str, scene_id: str, *, continuity_contract_version: str | None = None) -> None:
        if not shot_id or not scene_id:
            raise ValueError("Shot registration needs shot and scene ids")
        if continuity_contract_version not in {None, "1.0"}:
            raise ValueError(f"Unsupported continuity contract version: {continuity_contract_version}")
        shot = self.data["shots"].setdefault(shot_id, {"takes": {}, "selected": None})
        existing_scene_id = shot.get("scene_id")
        if existing_scene_id is not None and existing_scene_id != scene_id:
            raise ValueError(f"Shot {shot_id} is already registered to scene {existing_scene_id}")
        existing_version = shot.get("continuity_contract_version")
        if (continuity_contract_version is not None and existing_version is not None
                and existing_version != continuity_contract_version):
            raise ValueError(f"Shot {shot_id} already uses continuity contract {existing_version}")
        shot["scene_id"] = scene_id
        if continuity_contract_version is not None:
            shot["continuity_contract_version"] = continuity_contract_version
        self._save()

    def add_take(self, shot_id: str, take_id: str, path: str, duration_seconds: float, metadata: dict | None = None) -> None:
        if not shot_id or not take_id or duration_seconds <= 0:
            raise ValueError("Take needs shot id, take id and positive duration")
        media = self._media(path)
        if any(take.get("path") == media for shot in self.data["shots"].values() for take in shot.get("takes", {}).values()):
            raise ValueError(f"Take file is already registered: {media}")
        shot = self.data["shots"].setdefault(shot_id, {"takes": {}, "selected": None})
        if take_id in shot["takes"]:
            raise ValueError(f"Take already exists: {take_id}")
        shot["takes"][take_id] = {"path": media, "duration_seconds": duration_seconds, "metadata": metadata or {}}
        self._save()

    def link_assets(self, shot_id: str, asset_ids: list[str]) -> None:
        if not shot_id or any(asset_id not in self.data["assets"] for asset_id in asset_ids):
            raise ValueError("Shot id and known asset ids are required")
        shot = self.data["shots"].setdefault(shot_id, {"takes": {}, "selected": None})
        shot["asset_ids"] = list(dict.fromkeys(asset_ids))
        self._save()

    def register_refmod_asset(
        self,
        asset_id: str,
        *,
        project_id: str,
        project_path: str,
        loader_name: str,
        concept_type: str,
        source_sha256: str,
        extractor: Mapping[str, Any],
    ) -> None:
        """Record a project Mod and the approved visual asset it conditions."""
        asset = self.data["assets"].get(asset_id)
        if not isinstance(asset, Mapping):
            raise ValueError(f"Unknown RefMod source asset: {asset_id}")
        if asset.get("kind") not in {"character", "location", "prop"}:
            raise ValueError(f"RefMod source asset has an unsupported kind: {asset_id}")
        if not isinstance(concept_type, str) or concept_type not in {"identity", "clothing", "background", "generic", "style"}:
            raise ValueError(f"Unsupported RefMod concept type: {concept_type}")
        if not isinstance(extractor, Mapping):
            raise ValueError("RefMod extractor provenance must be a mapping")
        allowed_extractor_keys = {"tool", "node", "workflow_hash_sha256", "model_stack"}
        unknown_extractor_keys = set(extractor) - allowed_extractor_keys
        if unknown_extractor_keys:
            raise ValueError(
                "RefMod extractor provenance has unsupported fields: "
                + ", ".join(sorted(unknown_extractor_keys))
            )
        for key in ("tool", "node", "workflow_hash_sha256"):
            value = extractor.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"RefMod extractor provenance needs {key}")
        workflow_hash = extractor["workflow_hash_sha256"]
        if len(workflow_hash) != 64 or any(char not in "0123456789abcdef" for char in workflow_hash):
            raise ValueError("RefMod extractor workflow_hash_sha256 must be a lowercase SHA-256 digest")
        if "model_stack" in extractor and (
                not isinstance(extractor["model_stack"], list)
                or any(not isinstance(item, Mapping) for item in extractor["model_stack"])):
            raise ValueError("RefMod extractor model_stack must be a list of mappings")

        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("RefMod registration needs project_id")
        if not isinstance(source_sha256, str) or len(source_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in source_sha256
        ):
            raise ValueError("RefMod source_sha256 must be a lowercase SHA-256 digest")

        normalized_loader = str(loader_name).replace("\\", "/")
        loader_parts = PurePosixPath(normalized_loader).parts
        if (len(loader_parts) < 3 or loader_parts[0] != "openmontage"
                or any(part in {".", ".."} for part in loader_parts)):
            raise ValueError("RefMod loader name must stay under openmontage/<project_id>/")
        if loader_parts[1] != project_id:
            raise ValueError(
                "RefMod loader namespace does not match project_id"
            )

        source_path = self._media(asset["path"])
        actual_source_sha256 = self._sha256(self.root / source_path)
        if actual_source_sha256 != source_sha256:
            raise ValueError("Approved source changed during RefMod extraction")
        mod_path = self._media(project_path)
        if not mod_path.replace("\\", "/").startswith("assets/refmods/"):
            raise ValueError("RefMod project path must be under assets/refmods/")
        if Path(mod_path).suffix.lower() != ".safetensors":
            raise ValueError("RefMod project asset must use the .safetensors extension")

        record = {
            "project_id": project_id,
            "entity_id": str(asset.get("entity_id") or asset_id),
            "state": str(asset.get("state") or "default"),
            "concept_type": concept_type,
            "project_path": mod_path,
            "loader_name": normalized_loader,
            "source_path": source_path,
            "source_sha256": source_sha256,
            "refmod_sha256": self._sha256(self.root / mod_path),
            "status": "ready",
            "extractor": dict(extractor),
        }
        self.data.setdefault("refmod_assets", {})[asset_id] = record
        self._save()

    def record_refmod_usage(self, mode: str, *, route_id: str, decision_id: str) -> None:
        """Record the approved conditioning mode used for this asset batch."""
        if mode not in {"project_refmod", "native_ref2va"}:
            raise ValueError(f"Unsupported RefMod usage mode: {mode}")
        if not isinstance(route_id, str) or not route_id.strip():
            raise ValueError("RefMod usage needs a route_id")
        if not isinstance(decision_id, str) or not decision_id.strip():
            raise ValueError("RefMod usage needs a decision_id")
        self.data["refmod_usage"] = {
            "mode": mode,
            "route_id": route_id,
            "decision_id": decision_id,
        }
        self._save()

    def _refmod_is_current(self, asset_id: str, record: Mapping[str, Any]) -> bool:
        try:
            asset = self.data["assets"][asset_id]
            source_path = self._media(asset["path"])
            mod_path = self._media(record["project_path"])
        except (KeyError, TypeError, ValueError):
            return False
        expected_entity_id = str(asset.get("entity_id") or asset_id)
        expected_state = str(asset.get("state") or "default")
        project_id = record.get("project_id")
        loader_parts = PurePosixPath(
            str(record.get("loader_name", "")).replace("\\", "/")
        ).parts
        return (
            source_path == record.get("source_path")
            and expected_entity_id == record.get("entity_id")
            and expected_state == record.get("state")
            and (
                not project_id
                or (
                    len(loader_parts) >= 3
                    and loader_parts[0] == "openmontage"
                    and loader_parts[1] == project_id
                )
            )
            and self._sha256(self.root / source_path) == record.get("source_sha256")
            and self._sha256(self.root / mod_path) == record.get("refmod_sha256")
        )

    def _loader_copy_is_current(
        self, record: Mapping[str, Any], comfyui_workspace: str | Path
    ) -> bool:
        workspace = Path(comfyui_workspace).resolve()
        model_root = (workspace / "models" / "refmods").resolve()
        loader_name = str(record.get("loader_name", "")).replace("\\", "/")
        loader_path = (model_root / f"{loader_name}.safetensors").resolve()
        try:
            if not loader_path.is_relative_to(model_root):
                return False
            return (
                loader_path.is_file()
                and self._sha256(loader_path) == record.get("refmod_sha256")
            )
        except (OSError, ValueError):
            return False

    def refmods_for_shot(
        self,
        shot_id: str,
        *,
        comfyui_workspace: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Return current RefMods for linked assets in deterministic prompt order."""
        shot = self.data["shots"].get(shot_id)
        if not isinstance(shot, Mapping):
            raise ValueError(f"Unknown shot: {shot_id}")
        usage_mode = self.data.get("refmod_usage", {}).get("mode")
        if usage_mode == "native_ref2va":
            return []
        strict_project_mode = usage_mode == "project_refmod"
        refmod_assets = self.data.get("refmod_assets", {})
        records = []
        stale_asset_ids = []
        missing_asset_ids = []
        for asset_id in sorted(set(shot.get("asset_ids", []))):
            asset = self.data.get("assets", {}).get(asset_id)
            if not isinstance(asset, Mapping) or asset.get("kind") not in {
                "character", "location", "prop"
            }:
                continue
            record = refmod_assets.get(asset_id)
            if not isinstance(record, Mapping):
                if strict_project_mode:
                    missing_asset_ids.append(asset_id)
                continue
            if (
                not self._refmod_is_current(asset_id, record)
                or (
                    comfyui_workspace is not None
                    and not self._loader_copy_is_current(record, comfyui_workspace)
                )
            ):
                stale_asset_ids.append(asset_id)
                continue
            records.append({
                "asset_id": asset_id,
                "description": asset.get("description", ""),
                **record,
            })
        if stale_asset_ids and strict_project_mode:
            raise ValueError(
                "stale RefMod for linked approved assets in shot "
                f"{shot_id}: {', '.join(stale_asset_ids)}; re-extract before batching"
            )
        if missing_asset_ids and strict_project_mode:
            raise ValueError(
                "missing RefMod for linked approved assets in shot "
                f"{shot_id}: {', '.join(missing_asset_ids)}; extract before batching"
            )
        return [
            {**record, "prompt_label": f"<Picture {index}>"}
            for index, record in enumerate(records, start=1)
        ]

    def record_continuity_review(self, shot_id: str, take_id: str, review: Mapping[str, Any]) -> None:
        shot = self.data["shots"].get(shot_id)
        if not shot or take_id not in shot.get("takes", {}):
            raise ValueError(f"Unknown shot or take: {shot_id}/{take_id}")
        if not isinstance(review, Mapping):
            raise ValueError("Continuity review must be a mapping")

        expected_dimensions = (
            "identity_wardrobe",
            "location_anchors",
            "camera_continuity",
            "light_and_look",
            "story_state",
        )
        dimensions = review.get("dimensions")
        if not isinstance(dimensions, Mapping):
            raise ValueError("Continuity review dimensions are required")
        missing = [name for name in expected_dimensions if name not in dimensions]
        if missing:
            raise ValueError("Continuity review is missing dimensions: " + ", ".join(missing))
        unknown_dimensions = set(dimensions) - set(expected_dimensions)
        if unknown_dimensions:
            raise ValueError("Continuity review has unsupported dimension keys: " + ", ".join(sorted(unknown_dimensions)))
        valid_statuses = {"pass", "intentional_change", "drift", "unclear"}
        invalid = [name for name in expected_dimensions if not isinstance(dimensions[name], str) or dimensions[name] not in valid_statuses]
        if invalid:
            raise ValueError("Continuity review has invalid dimensions: " + ", ".join(invalid))

        notes = review.get("notes")
        if not isinstance(notes, Mapping):
            raise ValueError("Continuity review notes are required")
        missing_notes = [name for name in expected_dimensions if not isinstance(notes.get(name), str) or not notes[name].strip()]
        if missing_notes:
            raise ValueError("Continuity review is missing notes: " + ", ".join(missing_notes))
        unknown_notes = set(notes) - set(expected_dimensions)
        if unknown_notes:
            raise ValueError("Continuity review has unsupported note keys: " + ", ".join(sorted(unknown_notes)))

        evidence_paths = review.get("evidence_paths")
        if not isinstance(evidence_paths, list) or not evidence_paths:
            raise ValueError("Continuity review needs at least one evidence path")
        if any(not isinstance(path, (str, Path)) for path in evidence_paths):
            raise ValueError("Continuity review evidence paths must be project-relative file paths")
        normalized_evidence = [self._media(path) for path in evidence_paths]
        override_reason = review.get("override_reason")
        if override_reason is not None and (not isinstance(override_reason, str) or not override_reason.strip()):
            raise ValueError("Continuity override reason cannot be empty")

        allowed_keys = {"dimensions", "notes", "evidence_paths", "override_reason"}
        unknown = set(review) - allowed_keys
        if unknown:
            raise ValueError("Continuity review has unsupported fields: " + ", ".join(sorted(unknown)))

        record = {
            "reviewed_path": shot["takes"][take_id]["path"],
            "dimensions": dict(dimensions),
            "notes": dict(notes),
            "evidence_paths": normalized_evidence,
        }
        if override_reason is not None:
            record["override_reason"] = override_reason.strip()
        take_metadata = shot["takes"][take_id].setdefault("metadata", {})
        take_metadata["continuity_review"] = record
        self._save()

    def asset_manifest(self) -> dict[str, Any]:
        assets = []
        continuity_shots = {}
        continuity_reviews = {}
        refmod_assets = {
            asset_id: {
                **record,
                "status": "ready" if self._refmod_is_current(asset_id, record) else "stale",
            }
            for asset_id, record in self.data.get("refmod_assets", {}).items()
            if isinstance(record, Mapping)
        }
        for shot_id, shot in self.data["shots"].items():
            scene_id = shot.get("scene_id", shot_id)
            continuity_record = {"scene_id": scene_id}
            if shot.get("continuity_contract_version") is not None:
                continuity_record["continuity_contract_version"] = shot["continuity_contract_version"]
            continuity_shots[shot_id] = continuity_record
            for asset_id in shot.get("asset_ids", []):
                item = self.data["assets"][asset_id]
                assets.append({"id": f"asset:{quote(shot_id, safe='')}:{quote(asset_id, safe='')}", "type": "image", "path": self._media(item["path"]), "source_tool": item["metadata"].get("source_tool", "provided"), "scene_id": scene_id, "subtype": item["kind"], "generation_summary": item["description"]})
            if shot.get("selected"):
                take_id = shot["selected"]
                take = shot["takes"][take_id]
                item = {"id": f"take:{quote(shot_id, safe='')}:{quote(take_id, safe='')}", "type": "video", "path": self._media(take["path"]), "source_tool": take["metadata"].get("source_tool", "provided"), "scene_id": scene_id, "duration_seconds": take["duration_seconds"]}
                for key in ("seed", "prompt", "model", "provider"):
                    if key in take["metadata"]:
                        item[key] = take["metadata"][key]
                workflow_provenance = take.get("metadata", {}).get("workflow_provenance")
                if isinstance(workflow_provenance, Mapping):
                    bindings = workflow_provenance.get("refmod_assets")
                    asset_ids = workflow_provenance.get("refmod_asset_ids")
                    if isinstance(bindings, list) and bindings:
                        binding_ids = [
                            str(binding.get("asset_id"))
                            for binding in bindings
                            if isinstance(binding, Mapping)
                        ]
                        if len(binding_ids) != len(bindings):
                            raise ValueError(
                                f"Selected take {shot_id}/{take_id} has malformed RefMod provenance"
                            )
                        if asset_ids is None:
                            asset_ids = binding_ids
                        if asset_ids != binding_ids:
                            raise ValueError(
                                f"Selected take {shot_id}/{take_id} RefMod IDs do not match binding order"
                            )
                        item["refmod_asset_ids"] = list(asset_ids)
                        item["refmod_assets"] = [dict(binding) for binding in bindings]
                if "enhancement" in take.get("metadata", {}):
                    item["enhancement"] = take["metadata"]["enhancement"]
                assets.append(item)
                review = take.get("metadata", {}).get("continuity_review")
                if review and review.get("reviewed_path") == take["path"]:
                    if shot.get("continuity_contract_version") == "1.0":
                        dimensions = review.get("dimensions", {})
                        unresolved = isinstance(dimensions, Mapping) and any(
                            value in {"drift", "unclear"} for value in dimensions.values()
                        )
                        override_reason = review.get("override_reason")
                        if unresolved and (not isinstance(override_reason, str) or not override_reason.strip()):
                            raise ValueError(
                                f"Selected strict take {shot_id}/{take_id} needs a continuity override before export"
                            )
                    continuity_reviews[shot_id] = {"take_id": take_id, **review}
        selection = {shot_id: shot["selected"] for shot_id, shot in self.data["shots"].items() if shot.get("selected")}
        metadata = {
            "narrative_selection": selection,
            "continuity_shots": continuity_shots,
            "continuity_reviews": continuity_reviews,
            "refmod_assets": refmod_assets,
        }
        if isinstance(self.data.get("refmod_usage"), Mapping):
            metadata["refmod_usage"] = dict(self.data["refmod_usage"])
        return {"version": "1.0", "assets": assets, "metadata": metadata}

    def select_take(self, shot_id: str, take_id: str) -> None:
        shot = self.data["shots"].get(shot_id)
        if not shot or take_id not in shot["takes"]:
            raise ValueError(f"Unknown shot or take: {shot_id}/{take_id}")
        if shot.get("continuity_contract_version") == "1.0":
            take = shot["takes"][take_id]
            review = take.get("metadata", {}).get("continuity_review")
            if not isinstance(review, Mapping):
                raise ValueError(f"Strict continuity selection requires a continuity review: {shot_id}/{take_id}")
            if review.get("reviewed_path") != take.get("path"):
                raise ValueError(f"Continuity review is stale for the current take path: {shot_id}/{take_id}")
            dimensions = review.get("dimensions")
            if not isinstance(dimensions, Mapping):
                raise ValueError(f"Strict continuity selection has invalid review dimensions: {shot_id}/{take_id}")
            unresolved = any(value in {"drift", "unclear"} for value in dimensions.values())
            override_reason = review.get("override_reason")
            if unresolved and (not isinstance(override_reason, str) or not override_reason.strip()):
                raise ValueError(f"Continuity drift or unclear status needs an override before selection: {shot_id}/{take_id}")
            try:
                evidence_paths = review.get("evidence_paths", [])
                if not isinstance(evidence_paths, list) or not evidence_paths:
                    raise ValueError("missing evidence paths")
                for evidence_path in evidence_paths:
                    self._media(evidence_path)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Strict continuity selection has invalid review evidence: {shot_id}/{take_id}") from exc
        shot["selected"] = take_id
        self._save()

    def apply_enhancement(self, shot_id: str, take_id: str, path: str, *, duration_seconds: float, enhancement: dict[str, Any]) -> None:
        shot = self.data["shots"].get(shot_id)
        if not shot or shot.get("selected") != take_id or take_id not in shot.get("takes", {}):
            raise ValueError(f"Enhancement requires the selected take: {shot_id}/{take_id}")
        if duration_seconds <= 0:
            raise ValueError("Enhanced take needs a positive duration")
        media = self._media(path)
        take = shot["takes"][take_id]
        metadata = take.setdefault("metadata", {})
        metadata.setdefault("original_path", take["path"])
        metadata.pop("continuity_review", None)
        take["path"] = media
        take["duration_seconds"] = duration_seconds
        metadata["enhancement"] = dict(enhancement)
        self._save()

    def edit_decisions(self, shot_ids: list[str], render_runtime: str) -> dict[str, Any]:
        if render_runtime not in {"ffmpeg", "remotion", "hyperframes"} or not shot_ids:
            raise ValueError("A render runtime and at least one shot are required")
        cuts = []
        for shot_id in shot_ids:
            shot = self.data["shots"].get(shot_id)
            if not shot or not shot.get("selected"):
                raise ValueError(f"Shot has no selected take: {shot_id}")
            take = shot["takes"][shot["selected"]]
            source = self.root / self._media(take["path"])
            cuts.append({"id": shot_id, "source": str(source), "in_seconds": 0, "out_seconds": take["duration_seconds"]})
        selection = {shot_id: self.data["shots"][shot_id]["selected"] for shot_id in shot_ids}
        continuity_shots = {}
        for shot_id in shot_ids:
            shot = self.data["shots"][shot_id]
            scene = {"scene_id": shot.get("scene_id", shot_id)}
            if shot.get("continuity_contract_version") is not None:
                scene["continuity_contract_version"] = shot["continuity_contract_version"]
            continuity_shots[shot_id] = scene
        return {
            "version": "1.0",
            "render_runtime": render_runtime,
            "cuts": cuts,
            "metadata": {"narrative_selection": selection, "continuity_shots": continuity_shots},
        }
