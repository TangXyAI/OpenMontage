"""Video-model catalog and selection persistence.

This module is deliberately a thin, deterministic helper around the tool
registry and the decision log. It does not choose a route or write a prompt:
the agent presents the menu, the user approves, and only then does the agent
call :func:`record_selection`. The fixed priority order keeps local routes
first and makes a silent re-route visible in the audit trail.
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

DECISION_CATEGORY = "provider_selection"
DECISION_SUBJECT = "Video model and route"

_OPERATIONS_TEXT_IMAGE = ("text_to_video", "image_to_video")
_OPERATIONS_HYPERFLOW = (
    "text_to_video",
    "image_to_video",
    "first_last_frame_to_video",
    "reference_to_video",
)


@dataclass(frozen=True)
class VideoRoute:
    """One concrete way to satisfy a video-generation request.

    ``route`` is the runtime path inside the provider (for example
    ``comfyui/gguf``), while ``route_id`` is the stable id recorded in the
    decision log. ``model_family`` is the value a ComfyUI tool expects in its
    ``model_family`` input; cloud routes leave it empty.
    """

    route_id: str
    family: str
    route: str
    tool: str
    model: str
    priority: int
    local: bool
    operations: tuple[str, ...]
    notes: str
    model_family: str


def default_routes() -> list[VideoRoute]:
    """Return the fixed catalog, ordered local-first by priority."""
    return [
        VideoRoute(
            route_id="hyperflow_gguf",
            family="MiniMax H3 HyperFlow",
            route="comfyui/gguf",
            tool="comfyui_video",
            model="minimax_h3_hyperflow_local",
            priority=1,
            local=True,
            operations=_OPERATIONS_HYPERFLOW,
            notes="Q4_K_M local weights; safest on a 16 GB GPU; start here",
            model_family="minimax_h3_hyperflow_local",
        ),
        VideoRoute(
            route_id="hyperflow_int8",
            family="MiniMax H3 HyperFlow",
            route="comfyui/int8",
            tool="comfyui_video",
            model="minimax_h3_hyperflow_local",
            priority=2,
            local=True,
            operations=_OPERATIONS_HYPERFLOW,
            notes="INT8 local weights; faster, but may OOM on 16 GB",
            model_family="minimax_h3_hyperflow_local",
        ),
        VideoRoute(
            route_id="h3_local",
            family="MiniMax H3",
            route="comfyui/local",
            tool="comfyui_video",
            model="minimax_h3_local",
            priority=3,
            local=True,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="local MiniMax H3 without HyperFlow; more steps",
            model_family="minimax_h3_local",
        ),
        VideoRoute(
            route_id="minimax_direct",
            family="MiniMax H3",
            route="minimax/direct",
            tool="minimax_video",
            model="MiniMax-H3",
            priority=4,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="official MiniMax API",
            model_family="",
        ),
        VideoRoute(
            route_id="minimax_fal",
            family="MiniMax H3",
            route="fal/minimax-h3",
            tool="minimax_fal_video",
            model="hailuo-03",
            priority=5,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="MiniMax H3 through fal.ai",
            model_family="",
        ),
        VideoRoute(
            route_id="runway_h3",
            family="MiniMax H3",
            route="runway/hailuo3",
            tool="runway_video",
            model="hailuo3",
            priority=6,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="Hailuo 3 on Runway",
            model_family="",
        ),
        VideoRoute(
            route_id="atlas_h3",
            family="MiniMax H3",
            route="atlas/minimax-h3",
            tool="atlas_video",
            model="minimax/h3/text-to-video",
            priority=7,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="H3 through AtlasCloud",
            model_family="",
        ),
        VideoRoute(
            route_id="comfyui_h3_api",
            family="MiniMax H3",
            route="comfyui/partner-api",
            tool="comfyui_video",
            model="minimax_h3_api",
            priority=8,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="ComfyUI partner API nodes",
            model_family="minimax_h3_api",
        ),
        VideoRoute(
            route_id="h3_max",
            family="MiniMax H3 Max",
            route="h3max/direct",
            tool="h3_max_video",
            model="h3-max",
            priority=9,
            local=False,
            operations=(
                "text_to_video",
                "image_to_video",
                "reference_to_video",
            ),
            notes="H3 Max drafts and final clips with reference control",
            model_family="",
        ),
        VideoRoute(
            route_id="pika_h3_flex",
            family="Pika H3 Flex",
            route="pika/h3-flex",
            tool="pika_video",
            model="pika-h3-flex",
            priority=10,
            local=False,
            operations=(
                "text_to_video",
                "image_to_video",
                "reference_to_video",
            ),
            notes="cheapest draft route; up to 4K upload and 12 references",
            model_family="",
        ),
        VideoRoute(
            route_id="seedance_fal",
            family="Seedance 2.5",
            route="fal/seedance-2.5",
            tool="seedance_video",
            model="2.5",
            priority=11,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="Seedance 2.5 through fal.ai",
            model_family="",
        ),
        VideoRoute(
            route_id="seedance_ark",
            family="Seedance 2.5",
            route="ark/seedance-2.5",
            tool="seedance_ark",
            model="2.5",
            priority=12,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="Seedance 2.5 through Volcengine Ark",
            model_family="",
        ),
        VideoRoute(
            route_id="atlas_seedance",
            family="Seedance 2.5",
            route="atlas/seedance-2.5",
            tool="atlas_video",
            model="bytedance/seedance-2.5/text-to-video",
            priority=13,
            local=False,
            operations=_OPERATIONS_TEXT_IMAGE,
            notes="Seedance 2.5 through AtlasCloud",
            model_family="",
        ),
    ]


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


def _tool_cost(tool: Any, duration: int) -> float | None:
    if tool is None:
        return None
    try:
        return round(
            float(tool.estimate_cost({"prompt": "x", "duration": duration})), 2
        )
    except Exception:
        return None


def _tool_setup(tool: Any) -> str | None:
    if tool is None:
        return None
    try:
        return tool.get_info().get("install_instructions")
    except Exception:
        return None


# Local routes split the same ``comfyui_video`` tool status, so a machine with
# only one quantization installed would otherwise advertise both. These routes
# resolve their availability from the readiness variant instead.
_LOCAL_VARIANT_ROUTES = {
    "hyperflow_gguf": "gguf",
    "hyperflow_int8": "int8",
}


def _variant_readiness(
    readiness: Mapping[str, Any] | None, variant: str
) -> Mapping[str, Any] | None:
    """Return one quantization's readiness entry, or None when unavailable."""
    if not isinstance(readiness, Mapping):
        return None
    variants = readiness.get("variants")
    if not isinstance(variants, Mapping):
        return None
    state = variants.get(variant)
    return state if isinstance(state, Mapping) else None


def _variant_setup(state: Mapping[str, Any]) -> str:
    """Turn a variant's blockers into a ``setup`` hint."""
    blockers = [str(item) for item in (state.get("blockers") or []) if str(item)]
    if blockers:
        return "; ".join(blockers)
    return "Local route is not ready; check the HyperFlow readiness report"


def build_menu(
    registry: Any,
    *,
    duration: int = 5,
    readiness: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the live menu by combining the fixed catalog with registry state.

    ``readiness`` is the result of
    :func:`lib.local_video_readiness.check_hyperflow_readiness`. When supplied,
    ``hyperflow_gguf`` and ``hyperflow_int8`` take their availability from the
    matching ``readiness["variants"]`` entry, so a missing quantization is not
    advertised as available. ``h3_local`` and every cloud route keep reading
    the tool status, and omitting ``readiness`` restores that behavior for all
    local routes.
    """
    tools = getattr(registry, "_tools", {}) or {}
    menu: list[dict[str, Any]] = []
    for route in default_routes():
        tool = tools.get(route.tool)
        status = _tool_status(tool)
        tool_available = status == "available"
        available = tool_available
        variant = _LOCAL_VARIANT_ROUTES.get(route.route_id)
        variant_state = _variant_readiness(readiness, variant) if variant else None
        if variant_state is not None:
            variant_ready = bool(variant_state.get("ready"))
            # A local route needs both its quantization on disk and a usable
            # ComfyUI tool. Weights alone are not enough: a stopped server
            # cannot accept the job.
            available = variant_ready and tool_available
            status = "available" if available else "unavailable"
        cost = 0.0 if route.local else _tool_cost(tool, duration)
        if variant_state is not None:
            setup_parts: list[str] = []
            if not variant_state.get("ready"):
                setup_parts.append(_variant_setup(variant_state))
            if not tool_available:
                tool_hint = _tool_setup(tool) or (
                    "ComfyUI video tool is not registered; run registry.discover()"
                )
                if tool_hint not in setup_parts:
                    setup_parts.append(tool_hint)
            setup = "; ".join(setup_parts) or None
        else:
            setup = None if available else _tool_setup(tool)
        menu.append(
            {
                "route_id": route.route_id,
                "family": route.family,
                "route": route.route,
                "tool": route.tool,
                "model": route.model,
                "priority": route.priority,
                "local": route.local,
                "operations": list(route.operations),
                "notes": route.notes,
                "available": available,
                "status": status,
                "cost_5s": cost,
                "setup": setup,
            }
        )
    menu.sort(key=lambda item: (item["priority"], item["route_id"]))
    return menu


def _format_cost(cost: Any) -> str:
    if cost is None:
        return "cost unknown"
    return f"${float(cost):.2f}"


def render_menu(routes: Sequence[Mapping[str, Any]]) -> str:
    """Render one line per route, local-first, for the agent to present."""
    lines = []
    for item in sorted(
        routes, key=lambda route: (route.get("priority", 0), route.get("route_id", ""))
    ):
        lines.append(
            f"{item.get('priority')}. {item.get('route_id')} "
            f"{item.get('family')} {item.get('tool')} "
            f"{_format_cost(item.get('cost_5s'))} {item.get('status')} "
            f"— {item.get('notes', '')}"
        )
    return "\n".join(lines)


def require_selected_route(
    decision_log: Mapping[str, Any], route_id: str
) -> Mapping[str, Any]:
    """Return the latest approved selection, or raise if it does not match."""
    decisions = decision_log.get("decisions") or []
    matches = [
        decision
        for decision in decisions
        if decision.get("category") == DECISION_CATEGORY
        and decision.get("subject") == DECISION_SUBJECT
    ]
    if not matches:
        raise ValueError("No user-approved video model selection")
    decision = matches[-1]
    if decision.get("user_approved") is not True:
        raise ValueError("No user-approved video model selection")
    if decision.get("selected") != route_id:
        raise ValueError(
            "Video model route "
            f"'{decision.get('selected')}' does not match required route '{route_id}'"
        )
    return decision


def _route_id(route: Any) -> str:
    if isinstance(route, Mapping):
        return route["route_id"]
    return route.route_id


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
    route: Any,
    options: Sequence[Mapping[str, Any]],
    reason: str,
) -> dict[str, Any]:
    """Append an approved video-model decision and persist it atomically."""
    log_path = Path(path)
    selected_route = _route_id(route)
    options_considered = [dict(option) for option in options]
    if not any(
        option.get("option_id") == selected_route for option in options_considered
    ):
        raise ValueError(
            f"Selected route '{selected_route}' is not among options_considered"
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
        "category": DECISION_CATEGORY,
        "subject": DECISION_SUBJECT,
        "options_considered": options_considered,
        "selected": selected_route,
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
