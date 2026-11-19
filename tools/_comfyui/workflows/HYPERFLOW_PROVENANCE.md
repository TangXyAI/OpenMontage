# HyperFlow API Workflow Provenance

The four API-format ComfyUI workflows in this directory are bundled, unmodified,
from a third-party repository:

- Source repository: https://huggingface.co/BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI
- Source path: `workflows/api/`

## Bundled files

| Local file | Upstream file |
|---|---|
| `hyperflow_int8_t2v_api.json` | `hyperflow_int8_t2v_api.json` |
| `hyperflow_int8_i2v_api.json` | `hyperflow_int8_i2v_api.json` |
| `hyperflow_int8_flf2v_api.json` | `hyperflow_int8_flf2v_api.json` |
| `hyperflow_int8_ref2v_api.json` | `hyperflow_int8_ref2v_api.json` |

These are INT8 community workflows from
`BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI`. They are executed in ComfyUI API
format (`{"<id>": {"class_type": ..., "inputs": ...}}`) by the `comfyui_video`
tool with `model_family="minimax_h3_hyperflow_local"`.

## License

The workflows accompany HyperFlow weights that are a Model Derivative of
MiniMax-H3 and are governed by the **MiniMax H3 Community License**. Use in the
European Union, United Kingdom, South Korea, and the United States requires
authorization from MiniMax. Refer to the upstream repository and the MiniMax H3
Community License for the full terms.

## Relicensing

OpenMontage bundles these workflow JSON files for convenience only. OpenMontage
does **not** relicense them; they remain subject to the upstream repository's
terms and the `MiniMax H3 Community License`. No model weights are included in
this repository.
