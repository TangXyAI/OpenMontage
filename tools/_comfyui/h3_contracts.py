"""Live socket contracts used by OpenMontage's local H3 RefMod routes."""

from __future__ import annotations


_REFMOD_SLOT_INPUTS = {
    f"{prefix}_{slot}"
    for slot in range(1, 9)
    for prefix in ("mod", "strength", "copies")
}

REFMOD_VIDEO_NODE_INPUT_REQUIREMENTS: dict[str, set[str]] = {
    "MiniMaxH3ReferenceToVideo": {
        "clip", "vae", "audio_vae", "prompt", "width", "height", "length",
        "ref_image_size",
    },
    "MiniMaxH3RefModsLoader": {"show_info", "max_total_tokens", *_REFMOD_SLOT_INPUTS},
    "MiniMaxH3RefModTextEncode": {
        "clip", "mods", "prompt", "reference_fps", "max_total_tokens", "vae",
    },
    "BasicGuider": {"model", "conditioning"},
}

REFMOD_EXTRACTION_NODE_INPUT_REQUIREMENTS: dict[str, set[str]] = {
    "LoadImage": {"image"},
    "VAELoader": {"vae_name"},
    "MiniMaxH3RefModExtract": {
        "name", "mode", "concept_type", "background_retention", "vae",
        "ref_resolution", "pool_h", "pool_w", "latent_frames", "identity",
        "merge", "motion_only", "multiplier", "max_tokens", "extraction_preset",
        "subfolder", "description", "save", "budget_policy", "image_refs",
    },
}

LOCAL_H3_ROUTE_NODE_INPUT_REQUIREMENTS: dict[str, set[str]] = {
    **REFMOD_VIDEO_NODE_INPUT_REQUIREMENTS,
    **REFMOD_EXTRACTION_NODE_INPUT_REQUIREMENTS,
    "MiniMaxH3ImageToVideo": {
        "clip", "vae", "audio_vae", "prompt", "width", "height", "length",
    },
    "HyperFlowGGUFLoader": {"unet_name", "weights_in"},
    "HyperFlowINT8Loader": {"unet_name", "patcher"},
    "HyperFlowLoader": {"unet_name"},
    "HyperFlowSigmas": {"model", "steps"},
}
