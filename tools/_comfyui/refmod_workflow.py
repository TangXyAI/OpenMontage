"""Safe API-workflow binding for MiniMax H3 RefMod conditioning."""

from __future__ import annotations

import copy
import re
from typing import Any


_REF2VA_NODE = "MiniMaxH3ReferenceToVideo"
_FL2VA_NODE = "MiniMaxH3ImageToVideo"
_LOADER_NODE = "MiniMaxH3RefModsLoader"
_APPLY_NODE = "MiniMaxH3RefModApply"
_REFMODS_PER_LOADER = 8
_LOADER_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")


def _connection(value: Any) -> tuple[str, int] | None:
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    ):
        return value[0], value[1]
    return None


def _node(workflow: dict[str, Any], node_id: str, expected: str) -> dict[str, Any]:
    node = workflow.get(node_id)
    if not isinstance(node, dict) or node.get("class_type") != expected:
        raise ValueError(
            f"RefMod workflow node {node_id!r} must be {expected}"
        )
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"RefMod workflow node {node_id!r} has no inputs object")
    return node


def _unique_id(workflow: dict[str, Any], preferred: str) -> str:
    if preferred not in workflow:
        return preferred
    suffix = 2
    while f"{preferred}__{suffix}" in workflow:
        suffix += 1
    return f"{preferred}__{suffix}"


def _new_loader(loader_name_by_slot: list[str]) -> dict[str, Any]:
    inputs: dict[str, Any] = {"show_info": False, "max_total_tokens": 0}
    for slot in range(1, _REFMODS_PER_LOADER + 1):
        index = slot - 1
        inputs[f"mod_{slot}"] = (
            loader_name_by_slot[index] if index < len(loader_name_by_slot) else "(none)"
        )
        inputs[f"strength_{slot}"] = 1.0
        inputs[f"copies_{slot}"] = 1
    return {"class_type": _LOADER_NODE, "inputs": inputs}


def _new_apply(conditioning: list[Any], loader_id: str) -> dict[str, Any]:
    return {
        "class_type": _APPLY_NODE,
        "inputs": {
            "conditioning": conditioning,
            "mods": [loader_id, 0],
            "override": False,
            "retention": 1.0,
            "curve_direction": "constant",
            "scramble_seed": -1,
            "curve_shape": "linear",
            "curve_value": 1.0,
        },
    }


def _validate_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(refs, list):
        raise ValueError("refmod_assets must be a list")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    required = ("asset_id", "loader_name", "concept_type", "state", "description", "prompt_label")
    for index, ref in enumerate(refs, start=1):
        if not isinstance(ref, dict):
            raise ValueError(f"RefMod reference {index} must be an object")
        missing = [key for key in required if not isinstance(ref.get(key), str)]
        if missing:
            raise ValueError(
                f"RefMod reference {index} is missing string fields: {', '.join(missing)}"
            )
        asset_id = ref["asset_id"].strip()
        loader_name = ref["loader_name"].replace("\\", "/").strip()
        if not asset_id:
            raise ValueError(f"RefMod reference {index} has an empty asset_id")
        if asset_id in seen:
            raise ValueError(f"Duplicate RefMod asset_id: {asset_id}")
        seen.add(asset_id)
        if not _LOADER_NAME_RE.fullmatch(loader_name) or any(
            part in {".", ".."} for part in loader_name.split("/")
        ):
            raise ValueError(f"Invalid RefMod loader_name for {asset_id!r}")
        normalized.append({**ref, "asset_id": asset_id, "loader_name": loader_name})
    return normalized


def _find_conditioning_path(workflow: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    h3_nodes = [
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == _REF2VA_NODE
    ]
    if len(h3_nodes) != 1:
        raise ValueError(
            "RefMod workflow requires exactly one MiniMaxH3ReferenceToVideo "
            "Ref2VA conditioning node"
        )
    h3_id = h3_nodes[0]
    h3_node = _node(workflow, h3_id, _REF2VA_NODE)
    if "prompt" not in h3_node["inputs"]:
        raise ValueError(f"Ref2VA conditioning node {h3_id!r} is missing input 'prompt'")

    apply_ids = {
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == _APPLY_NODE
    }
    conditioning_consumers = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        if node.get("class_type") == _APPLY_NODE:
            continue
        conditioning = _connection(node["inputs"].get("conditioning"))
        if conditioning and conditioning[0] in ({h3_id} | apply_ids):
            conditioning_consumers.append((str(node_id), node, conditioning))
    if len(conditioning_consumers) != 1:
        raise ValueError(
            "RefMod workflow requires exactly one Ref2VA conditioning consumer"
        )
    _sink_id, sink, connection = conditioning_consumers[0]
    if connection[1] != 0:
        raise ValueError("Ref2VA conditioning must use output 0")
    return h3_id, sink


def _existing_chain(
    workflow: dict[str, Any], h3_id: str, sink: dict[str, Any]
) -> list[tuple[str, str]]:
    loaders = {
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == _LOADER_NODE
    }
    applies = {
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == _APPLY_NODE
    }
    if not loaders and not applies:
        return []
    if not loaders or not applies or len(loaders) != len(applies):
        raise ValueError("RefMod workflow has an incomplete loader/apply chain")

    chain: list[tuple[str, str]] = []
    used_loaders: set[str] = set()
    current = _connection(sink["inputs"].get("conditioning"))
    visited: set[str] = set()
    while current and current[0] in applies:
        apply_id = current[0]
        if current[1] != 0 or apply_id in visited:
            raise ValueError("RefMod workflow has a cyclic or invalid apply connection")
        visited.add(apply_id)
        apply_node = _node(workflow, apply_id, _APPLY_NODE)
        loader_connection = _connection(apply_node["inputs"].get("mods"))
        conditioning_connection = _connection(apply_node["inputs"].get("conditioning"))
        if (
            loader_connection is None
            or loader_connection[0] not in loaders
            or loader_connection[1] != 0
            or conditioning_connection is None
            or conditioning_connection[1] != 0
        ):
            raise ValueError("RefMod workflow has invalid loader/apply connections")
        loader_id = loader_connection[0]
        if loader_id in used_loaders:
            raise ValueError("RefMod workflow reuses a loader in more than one apply node")
        used_loaders.add(loader_id)
        chain.append((apply_id, loader_id))
        current = conditioning_connection

    if current != (h3_id, 0):
        raise ValueError(
            "RefMod workflow chain does not terminate at the Ref2VA conditioning node"
        )
    if visited != applies or used_loaders != loaders:
        raise ValueError("RefMod workflow contains an unconnected loader/apply node")
    chain.reverse()
    return chain


def build_refmod_workflow(
    workflow: dict[str, Any],
    refs: list[dict[str, str]],
    operation: str,
) -> tuple[dict[str, Any], list[str]]:
    """Attach ordered RefMods to one supported local H3 Ref2VA graph.

    Existing workflows without RefMods are returned as deep copies unchanged.
    With RefMods, a validated loader/apply chain is either reused or injected
    between the official H3 Ref2VA conditioning node and its BasicGuider.
    """
    if not refs:
        return copy.deepcopy(workflow), []
    if operation == "first_last_frame_to_video":
        raise ValueError("RefMods are incompatible with FL2VA first/last-frame conditioning")
    if operation != "reference_to_video":
        raise ValueError("Local RefMods require a MiniMax H3 Ref2VA reference_to_video workflow")
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("RefMod workflow must be a non-empty API-format graph")

    normalized_refs = _validate_refs(refs)
    result = copy.deepcopy(workflow)
    h3_id, sink = _find_conditioning_path(result)
    chain = _existing_chain(result, h3_id, sink)
    if not chain and _connection(sink["inputs"].get("conditioning")) != (h3_id, 0):
        raise ValueError(
            "RefMod workflow BasicGuider is not connected to the Ref2VA conditioning node"
        )

    groups = [
        normalized_refs[start : start + _REFMODS_PER_LOADER]
        for start in range(0, len(normalized_refs), _REFMODS_PER_LOADER)
    ]
    group_count = max(len(groups), len(chain))
    h3_connection: list[Any] = [h3_id, 0]
    for group_index in range(1, group_count + 1):
        group = groups[group_index - 1] if group_index <= len(groups) else []
        if group_index <= len(chain):
            apply_id, loader_id = chain[group_index - 1]
        else:
            apply_id = _unique_id(result, f"refmod_apply_{group_index}")
            loader_id = _unique_id(result, f"refmod_loader_{group_index}")
            result[loader_id] = _new_loader([])
            result[apply_id] = _new_apply(h3_connection, loader_id)

        loader = _node(result, loader_id, _LOADER_NODE)
        apply_node = _node(result, apply_id, _APPLY_NODE)
        if group_index > len(chain):
            apply_node["inputs"]["conditioning"] = list(h3_connection)
            apply_node["inputs"]["mods"] = [loader_id, 0]

        for slot in range(1, _REFMODS_PER_LOADER + 1):
            loader["inputs"][f"mod_{slot}"] = "(none)"
            loader["inputs"][f"strength_{slot}"] = 1.0
            loader["inputs"][f"copies_{slot}"] = 1
        for slot, ref in enumerate(group, start=1):
            loader["inputs"][f"mod_{slot}"] = ref["loader_name"]

        h3_connection = [apply_id, 0]

    sink["inputs"]["conditioning"] = h3_connection
    return result, [ref["asset_id"] for ref in normalized_refs]
