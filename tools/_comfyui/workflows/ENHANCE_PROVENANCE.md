# 后期增强工作流来源与改动（ENHANCE_PROVENANCE）

本目录下两个 API 格式 ComfyUI 工作流供 OpenMontage 本地后期增强使用：

- `enhance_face_refine_h3_api.json`（face_refine，输出节点 `"23"`）
- `enhance_seedvr2_3b_api.json`（video_upscale，输出节点 `"23"`）

## 来源

| 本地文件 | 上游仓库 | 上游工作流 |
|---|---|---|
| `enhance_face_refine_h3_api.json` | [`Carasibana/ComfyUI-H3-FaceRefine`](https://github.com/Carasibana/ComfyUI-H3-FaceRefine) | `example_workflows/H3_Face_Refine_Auto_Select.json` |
| `enhance_seedvr2_3b_api.json` | [`numz/ComfyUI-SeedVR2_VideoUpscaler`](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler) | `example_workflows/SeedVR2_HD_video_upscale.json` |

两个文件均由 ComfyUI 前端从上述上游工作流**导出为 API 格式**（`{"<id>": {"class_type": ..., "inputs": ...}}`），再由 OpenMontage 做本机适配补丁，不包含模型权重或媒体素材。

## 本机补丁

### FaceRefine（`enhance_face_refine_h3_api.json`）

- 源视频：节点 `"1"`（`VHS_LoadVideoPath`）的 `video` 清空（原为本机 smoke 测试片路径），运行时写入实际输入。
- 参考图：节点 `"6"` / `"7"`（`LoadImage`）的 `image` 清空，运行时由管线写入角色参考图。
- 提示词：节点 `"9"`（`MiniMaxH3ReferenceToVideo`）的 `prompt` 清空，移除上游示例中的 smoke 测试角色描述，运行时由调用方传入完整 `subject_definitions` 段落。
- 输出：节点 `"23"`（`VHS_VideoCombine`）的 `filename_prefix` 改为 `om_enhance/face_refine`；`frame_rate` 固定为 `24`，运行时绑定源视频帧率。
- 检测器：节点 `"2"`（`H3FaceTrackCrop`）使用 `detector="face_yolov8n.pt"`、`fallback_detector="none"`、`identity_model="insightface"`。
- 去噪乘数：节点 `"31"`（`H3PerFrameDenoise`）的 `denoise_multiplier_small_face` / `denoise_multiplier_large_face` 均为 `1.0`，适配约 180px 的人脸。
- 模型节点（UNET/CLIP/VAE/LoRA）指向本机已安装文件。

### SeedVR2 3B（`enhance_seedvr2_3b_api.json`）

- 源视频：节点 `"21"`（`LoadVideo`）的 `file` 清空（原为本机 smoke 测试片文件名），运行时写入实际输入。
- 输出：节点 `"23"`（`SaveVideo`）的 `filename_prefix` 改为 `om_enhance/seedvr2`。
- 模型：DiT 使用官方 3B FP8，VAE 使用 `ema_vae_fp16`；分辨率短边 `1080`、`batch_size=5`、`temporal_overlap=3`。

## 默认可覆盖的模型文件名

以下均为工作流中的默认值，可在运行时按本机安装情况覆盖：

| 工作流 | 节点 | 用途 | 默认文件名 |
|---|---|---|---|
| FaceRefine | `"108"` | H3 UNET | `Minimax-h3_Singularity_ref2va_v2_int8.safetensors` |
| FaceRefine | `"109"` | 文本编码器 CLIP | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| FaceRefine | `"4"` | 视频 VAE | `minimax_h3_video_vae_fp16.safetensors` |
| FaceRefine | `"5"` | 音频 VAE | `minimax_h3_audio_vae_fp32.safetensors` |
| FaceRefine | `"12"` | Turbo LoRA | `MiniMax-H3\加速\PikaFlex-Turbo-8步高清多模态参考视频加速.safetensors` |
| FaceRefine | `"2"` | 人脸检测器 | `face_yolov8n.pt` |
| SeedVR2 | `"14"` | DiT 模型 | `seedvr2_ema_3b_fp8_e4m3fn.safetensors` |
| SeedVR2 | `"13"` | VAE 模型 | `ema_vae_fp16.safetensors` |

## 许可提示

- **H3 / MiniMax H3**：FaceRefine 工作流驱动的 H3 权重属于 MiniMax-H3 的模型衍生品，受 **MiniMax H3 Community License** 约束；在欧盟、英国、韩国和美国使用需获得 MiniMax 授权。上游 `ComfyUI-H3-FaceRefine` 代码本身为 MIT License。
- **SeedVR2**：上游 `ComfyUI-SeedVR2_VideoUpscaler` 代码为 Apache License 2.0（与 ByteDance Seed 项目保持一致）；SeedVR2 模型权重遵循其各自上游模型卡与许可条款，首次使用由节点自动下载。
- 本仓库仅内置工作流 JSON 以便复用，**不对其重新授权**；工作流仍受上游仓库及模型许可约束。

## 权重与素材

本仓库**不包含任何模型权重或媒体素材**。使用时需用户自行安装或由 ComfyUI 节点按默认文件名自动下载。
