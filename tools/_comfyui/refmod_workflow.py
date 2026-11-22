"""Safe API-workflow binding for MiniMax H3 RefMod conditioning."""

from __future__ import annotations

import copy
import re
from typing import Any


_REF2VA_NODE = "MiniMaxH3ReferenceToVideo"
_FL2VA_NODE = "MiniMaxH3ImageToVideo"
_LOADER_NODE = "MiniMaxH3RefModsLoader"
_APPLY_NODE = "MiniMaxH3RefModApply"
_TEXT_ENCODE_NODE = "MiniMaxH3RefModTextEncode"
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


def _new_text_encoder(
    h3_inputs: dict[str, Any], loader_id: str, prompt: str
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "clip": copy.deepcopy(h3_inputs["clip"]),
        "mods": [loader_id, 0],
        "prompt": prompt,
        "reference_fps": 24.0,
        "max_total_tokens": 0,
    }
    if "vae" in h3_inputs:
        inputs["vae"] = copy.deepcopy(h3_inputs["vae"])
    return {
        "class_type": _TEXT_ENCODE_NODE,
        "inputs": inputs,
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
        expected_label = f"<Picture {index}>"
        if ref["prompt_label"] != expected_label:
            raise ValueError(
                f"RefMod prompt_label order mismatch for {asset_id!r}; "
                f"expected {expected_label}"
            )
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

    conditioning_sources = {
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict)
        and node.get("class_type") in {_APPLY_NODE, _TEXT_ENCODE_NODE}
    }
    conditioning_consumers = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        if node.get("class_type") in {_APPLY_NODE, _TEXT_ENCODE_NODE}:
            continue
        conditioning = _connection(node["inputs"].get("conditioning"))
        if conditioning and conditioning[0] in ({h3_id} | conditioning_sources):
            conditioning_consumers.append((str(node_id), node, conditioning))
    if len(conditioning_consumers) != 1:
        raise ValueError(
            "RefMod workflow requires exactly one Ref2VA conditioning consumer"
        )
    _sink_id, sink, connection = conditioning_consumers[0]
    if connection[1] != 0:
        raise ValueError("Ref2VA conditioning must use output 0")
    return h3_id, sink


def _existing_text_encode(
    workflow: dict[str, Any], h3_id: str, sink: dict[str, Any]
) -> tuple[str, str] | None:
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
    encoders = {
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == _TEXT_ENCODE_NODE
    }
    if applies:
        raise ValueError(
            "Legacy RefMod Apply graphs do not bind prompt labels; use H3 RefMod Text Encode"
        )
    if not loaders and not encoders:
        return None
    if len(loaders) != 1 or len(encoders) != 1:
        raise ValueError("RefMod workflow requires one linked loader and Text Encode node")

    loader_id = next(iter(loaders))
    encoder_id = next(iter(encoders))
    if _connection(sink["inputs"].get("conditioning")) != (encoder_id, 0):
        raise ValueError("RefMod Text Encode output is not connected to the Ref2VA guider")
    loader = _node(workflow, loader_id, _LOADER_NODE)
    encoder = _node(workflow, encoder_id, _TEXT_ENCODE_NODE)
    h3_node = _node(workflow, h3_id, _REF2VA_NODE)
    if _connection(encoder["inputs"].get("mods")) != (loader_id, 0):
        raise ValueError("RefMod Text Encode is not connected to its loader")
    for key in ("clip", "vae"):
        if _connection(encoder["inputs"].get(key)) != _connection(h3_node["inputs"].get(key)):
            raise ValueError(f"RefMod Text Encode {key} input must match the Ref2VA graph")
    if not isinstance(encoder["inputs"].get("prompt"), str):
        raise ValueError("RefMod Text Encode is missing input 'prompt'")
    return encoder_id, loader_id


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
    if len(normalized_refs) > _REFMODS_PER_LOADER:
        raise ValueError(
            "The installed H3 RefMod Text Encode loader supports at most 8 "
            "mapped assets per shot"
        )
    result = copy.deepcopy(workflow)
    h3_id, sink = _find_conditioning_path(result)
    h3_node = _node(result, h3_id, _REF2VA_NODE)
    native_reference_inputs = [
        key
        for key, value in h3_node["inputs"].items()
        if key.startswith(("ref_images.", "ref_videos.", "ref_audios.", "ref_video_audios."))
        and _connection(value) is not None
    ]
    if native_reference_inputs:
        raise ValueError(
            "The installed H3 RefMod Text Encode cannot map project RefMods "
            "together with native image/motion references; choose one Ref2VA reference path"
        )
    chain = _existing_text_encode(result, h3_id, sink)
    if chain is None and _connection(sink["inputs"].get("conditioning")) != (h3_id, 0):
        raise ValueError(
            "RefMod workflow consumer is not connected to the Ref2VA conditioning node"
        )

    if chain is None:
        loader_id = _unique_id(result, "refmod_loader_1")
        encoder_id = _unique_id(result, "refmod_text_encode_1")
        result[loader_id] = _new_loader([])
        result[encoder_id] = _new_text_encoder(
            h3_node["inputs"], loader_id, str(h3_node["inputs"]["prompt"])
        )
    else:
        encoder_id, loader_id = chain
        encoder = _node(result, encoder_id, _TEXT_ENCODE_NODE)
        prompt = h3_node["inputs"].get("prompt")
        if not isinstance(prompt, str) or not prompt:
            prompt = encoder["inputs"].get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("RefMod Text Encode is missing input 'prompt'")
        encoder["inputs"]["prompt"] = prompt

    encoder = _node(result, encoder_id, _TEXT_ENCODE_NODE)
    loader = _node(result, loader_id, _LOADER_NODE)
    prompt = encoder["inputs"].get("prompt")
    labels = [ref["prompt_label"] for ref in normalized_refs]
    positions = [prompt.find(label) if isinstance(prompt, str) else -1 for label in labels]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise ValueError(
            "RefMod prompt is missing or misorders its <Picture N> labels"
        )

    for slot in range(1, _REFMODS_PER_LOADER + 1):
        loader["inputs"][f"mod_{slot}"] = "(none)"
        loader["inputs"][f"strength_{slot}"] = 1.0
        loader["inputs"][f"copies_{slot}"] = 1
    for slot, ref in enumerate(normalized_refs, start=1):
        loader["inputs"][f"mod_{slot}"] = ref["loader_name"]
    encoder["inputs"]["mods"] = [loader_id, 0]
    encoder["inputs"]["clip"] = copy.deepcopy(h3_node["inputs"]["clip"])
    encoder["inputs"]["vae"] = copy.deepcopy(h3_node["inputs"]["vae"])
    h3_node["inputs"]["prompt"] = ""
    sink["inputs"]["conditioning"] = [encoder_id, 0]
    return result, [ref["asset_id"] for ref in normalized_refs]
