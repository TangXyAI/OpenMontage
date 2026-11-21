"""Post-enhancement route menu and decision-log persistence.

This module mirrors :mod:`lib.video_model_selection` for the local
post-enhancement routes. It is a thin, deterministic helper: the agent offers
the menu, the user approves one route, and only then does the agent call
:func:`record_selection`. The fixed order keeps ``none`` first and both local
ComfyUI routes visible, so a silent re-route stays auditable.

Availability combines three sources:

* the ``comfyui_enhance`` tool must be registered and report ``available``;
* the ComfyUI server must be running (passed through ``readiness``);
* the matching readiness route (``face_refine`` / ``video_upscale``) must be
  ready on disk.

``estimate_source`` is deliberately honest: the face-refine time is a
placeholder, while the SeedVR2 scale is measured.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "artifacts"
    / "decision_log.schema.json"
)

ENHANCEMENT_CATEGORY = "enhancement_selection"
ENHANCEMENT_SUBJECT = "Post-enhancement route"

ENHANCEMENT_TOOL = "comfyui_enhance"


@dataclass(frozen=True)
class EnhancementRoute:
    """One selectable post-enhancement route.

    ``operation`` is the ``comfyui_enhance`` operation to run and doubles as
    the key into ``readiness["routes"]``. ``none`` carries neither, since it
    performs no work.
    """

    route_id: str
    label: str
    tool: str | None
    operation: str | None
    estimate_source: str


# Order is part of the contract: ``none`` first, then face refine, then the
# SeedVR2 upscale route.
ROUTES: tuple[EnhancementRoute, ...] = (
    EnhancementRoute(
        route_id="none",
        label="No enhancement",
        tool=None,
        operation=None,
        estimate_source="fixed",
    ),
    EnhancementRoute(
        route_id="face_refine",
        label="Face refine",
        tool=ENHANCEMENT_TOOL,
        operation="face_refine",
        estimate_source="placeholder",
    ),
    EnhancementRoute(
        route_id="seedvr2_upscale",
        label="SeedVR2 upscale",
        tool=ENHANCEMENT_TOOL,
        operation="video_upscale",
        estimate_source="measured_scale",
    ),
)


def _tool_status(tool: Any) -> str:
    """Read a tool's status as a lowercase string, defaulting to unavailable."""
    if tool is None:
        return "unavailable"
    try:
        raw_status = tool.get_status()
    except Exception:
        return "unavailable"
    value = getattr(raw_status, "value", None)
    return str(value if value is not None else raw_status).lower()


def _estimate_seconds(route_id: str, duration_seconds: float) -> int:
    """Return the estimated wall-clock seconds for one route."""
    if route_id == "none":
        return 0
    if route_id == "face_refine":
        return round(120 + 60 * duration_seconds)
    return round(30 + 178 * duration_seconds)


def _route_readiness(
    readiness: Mapping[str, Any] | None, operation: str
) -> Mapping[str, Any] | None:
    if not isinstance(readiness, Mapping):
        return None
    routes = readiness.get("routes")
    if not isinstance(routes, Mapping):
        return None
    state = routes.get(operation)
    return state if isinstance(state, Mapping) else None


def build_menu(
    registry: Any,
    readiness: Mapping[str, Any] | None,
    *,
    duration_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    """Build the enhancement menu by combining registry and readiness state.

    ``readiness`` is the result of
    :func:`lib.local_enhancement_readiness.check_enhancement_readiness`.
    ``none`` is always available. Every other route needs the registered tool,
    a running server, and a ready route; ``reason`` aggregates whatever is
    missing.
    """
    tools = getattr(registry, "_tools", {}) or {}
    server_running = bool(
        readiness.get("server_running") if isinstance(readiness, Mapping) else False
    )

    menu: list[dict[str, Any]] = []
    for route in ROUTES:
        available = True
        reasons: list[str] = []

        if route.tool is not None:
            tool = tools.get(route.tool)
            if tool is None:
                available = False
                reasons.append(f"{route.tool} tool is not registered")
            else:
                status = _tool_status(tool)
                if status != "available":
                    available = False
                    reasons.append(
                        f"{route.tool} tool is not available (status: {status})"
                    )

        if route.operation is not None:
            if not server_running:
                available = False
                reasons.append("ComfyUI server is not running")
            state = _route_readiness(readiness, route.operation)
            if state is None:
                available = False
                reasons.append(
                    f"No readiness report for {route.operation} route"
                )
            elif not state.get("ready"):
                available = False
                blockers = [
                    str(item) for item in (state.get("blockers") or []) if str(item)
                ]
                if blockers:
                    reasons.extend(blockers)
                else:
                    reasons.append(f"{route.operation} route is not ready")

        menu.append(
            {
                "route_id": route.route_id,
                "label": route.label,
                "tool": route.tool,
                "operation": route.operation,
                "available": available,
                "reason": "; ".join(reasons),
                "estimated_seconds": _estimate_seconds(
                    route.route_id, duration_seconds
                ),
                "estimate_source": route.estimate_source,
            }
        )
    return menu


def _next_decision_id(decisions: Sequence[Mapping[str, Any]]) -> str:
    highest = 0
    for decision in decisions:
        match = re.fullmatch(r"d-(\d+)", str(decision.get("decision_id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"d-{highest + 1:03d}"


def _atomic_write(path: Path, log: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(log, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise


def record_selection(
    path: str | Path,
    project_id: str,
    stage: str,
    route_id: str,
    options: Sequence[Mapping[str, Any]],
    reason: str,
) -> dict[str, Any]:
    """Append an approved enhancement decision and persist it atomically."""
    log_path = Path(path)
    options_considered = [dict(option) for option in options]
    if not any(
        option.get("option_id") == route_id for option in options_considered
    ):
        raise ValueError(
            f"Selected route '{route_id}' is not among options_considered"
        )

    if log_path.exists():
        with open(log_path, encoding="utf-8") as handle:
            log = json.load(handle)
    else:
        log = {"version": "1.0", "project_id": project_id, "decisions": []}

    decisions = log.setdefault("decisions", [])
    decision = {
        "decision_id": _next_decision_id(decisions),
        "stage": stage,
        "category": ENHANCEMENT_CATEGORY,
        "subject": ENHANCEMENT_SUBJECT,
        "options_considered": options_considered,
        "selected": route_id,
        "reason": reason,
        "user_visible": True,
        "user_approved": True,
    }
    decisions.append(decision)

    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    jsonschema.validate(log, schema)

    _atomic_write(log_path, log)
    return decision


def require_selected_route(
    decision_log: Mapping[str, Any],
    route_id: str,
) -> Mapping[str, Any]:
    """Return the latest approved enhancement selection, or raise."""
    decisions = decision_log.get("decisions") or []
    matches = [
        decision
        for decision in decisions
        if decision.get("category") == ENHANCEMENT_CATEGORY
        and decision.get("subject") == ENHANCEMENT_SUBJECT
    ]
    if not matches:
        raise ValueError("No user-approved enhancement route selection")
    decision = matches[-1]
    if decision.get("user_approved") is not True:
        raise ValueError("No user-approved enhancement route selection")
    if decision.get("selected") != route_id:
        raise ValueError(
            "Enhancement route "
            f"'{decision.get('selected')}' does not match required route "
            f"'{route_id}'"
        )
    return decision
