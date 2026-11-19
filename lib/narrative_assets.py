"""Persistent reference assets and explicitly selected shot takes.

This module stores production facts; creative selection remains with the agent
and the user. Paths in the catalog are relative to the project root.
"""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
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

    def put_asset(self, asset_id: str, kind: str, description: str, path: str, *, state: str = "default", metadata: dict | None = None) -> None:
        if not asset_id or kind not in {"character", "location", "prop"}:
            raise ValueError("Asset needs an id and kind character, location, or prop")
        if asset_id in self.data["assets"]:
            raise ValueError(f"Asset already exists: {asset_id}")
        self.data["assets"][asset_id] = {"kind": kind, "description": description, "path": self._media(path), "state": state, "metadata": metadata or {}}
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

    def asset_manifest(self) -> dict[str, Any]:
        assets = []
        for shot_id, shot in self.data["shots"].items():
            for asset_id in shot.get("asset_ids", []):
                item = self.data["assets"][asset_id]
                assets.append({"id": f"asset:{quote(shot_id, safe='')}:{quote(asset_id, safe='')}", "type": "image", "path": self._media(item["path"]), "source_tool": item["metadata"].get("source_tool", "provided"), "scene_id": shot_id, "subtype": item["kind"], "generation_summary": item["description"]})
            if shot.get("selected"):
                take_id = shot["selected"]
                take = shot["takes"][take_id]
                item = {"id": f"take:{quote(shot_id, safe='')}:{quote(take_id, safe='')}", "type": "video", "path": self._media(take["path"]), "source_tool": take["metadata"].get("source_tool", "provided"), "scene_id": shot_id, "duration_seconds": take["duration_seconds"]}
                for key in ("seed", "prompt", "model", "provider"):
                    if key in take["metadata"]:
                        item[key] = take["metadata"][key]
                assets.append(item)
        selection = {shot_id: shot["selected"] for shot_id, shot in self.data["shots"].items() if shot.get("selected")}
        return {"version": "1.0", "assets": assets, "metadata": {"narrative_selection": selection}}

    def select_take(self, shot_id: str, take_id: str) -> None:
        shot = self.data["shots"].get(shot_id)
        if not shot or take_id not in shot["takes"]:
            raise ValueError(f"Unknown shot or take: {shot_id}/{take_id}")
        shot["selected"] = take_id
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
        return {"version": "1.0", "render_runtime": render_runtime, "cuts": cuts, "metadata": {"narrative_selection": selection}}
