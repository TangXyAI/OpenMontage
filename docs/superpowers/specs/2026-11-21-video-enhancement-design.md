# 视频后期增强接入流水线 — 设计文档

- 日期：2026-11-21
- 状态：待批准（设计稿）
- 关联：`docs/hell-grind-integration.md`、`docs/superpowers/plans/2026-11-19-hell-grind-integration.md`
- 实验记录：`projects/_h3-api-export/STATUS.md`（本机，不入库）

---

## 1. 背景与目标

Hell-Grind 整合的本地 H3 试点已经跑通：Scene 73.6 六条 take、$0、20 秒成片。试点暴露的主要质量缺口是**生成画面的脸部细节**和**低分辨率源片**（640×352）。

2026-11-20 夜在本机验证了两条后期路线：

| 路线 | 结果 | 耗时（实测） |
|---|---|---|
| 官方 H3-FaceRefine | 五官/皮肤最锐；身份轻微漂移 | 未精确计时 |
| SeedVR2 3B FP8 | 整体自然、身份最接近原片；锐度低于 FaceRefine | 73 帧 / 3.04 秒 / 1080 short edge ≈ 9 分钟 |
| H3-FaceRefine-Plus | 受阻：`nvidia-vfx` 无 cp313 轮子 | — |

**目标**：把前两条路线变成流水线里的正式能力——在 `cinematic` 的 `assets` 阶段、选中 take 之后、导出 `asset_manifest` 之前，由用户选择增强路线；选择写入 `decision_log`；增强结果和溯源写进资产清单；把实验结论沉淀为技能文档。以后不再手工拼 ComfyUI 工作流。

### 已确定的用户决定

1. **作用位置（方案 A）**：先增强**选中的 take**，再进 `edit`。不在成片后跑。
2. **工具形态（方案 1）**：新增独立工具 `comfyui_enhance` + `assets` 子门禁，不复用 `comfyui_video` 的自定义工作流路径，也不把 ComfyUI 塞进现有 `upscale`/`face_restore`。

---

## 2. 目标 / 非目标 / 反目标

### 目标

- 新增可被 registry 发现的 `enhancement` 能力，provider 为 `comfyui`。
- 支持两种操作：`face_refine`（H3-FaceRefine）与 `video_upscale`（SeedVR2 3B FP8）。
- 提供离线就绪检查（文件系统级），菜单能区分"可用 / 缺节点 / 缺模型 / 服务未启动"。
- 在 `cinematic` 的 `assets` 阶段增加人工门禁 `enhancement_selection`，菜单含 `none / face_refine / seedvr2_upscale`，记录决策。
- 增强产物写入项目工作区，`asset_manifest` 记录来源 take、工具、模型、参数、分辨率。
- 新增 `skills/creative/video-enhancement.md`，写清两条路线的取舍、适用镜头、实测数据与禁止事项。
- 全程本地、零 API 成本；不引入云端增强。

### 非目标

- 不做 FaceRefine-Plus / nvidia-vfx / RTX VSR（cp313 阻塞，留待未来）。
- 不自动增强；没有用户选择就不运行。
- 不在同一次运行里串联两种操作（先超分再修脸留作未来评估）。
- 不增强未选中的候选 take（先选后增强）。
- 不支持任意自定义工作流覆盖（v1 只内置两个工作流）。
- 不改动其他流水线（`hybrid`、`animation` 等）的阶段定义；工具本身可被它们发现，但门禁只在 `cinematic` 落地。

### 反目标（即使技术上能跑也算失败）

- 静默增强：没有 `decision_log` 记录就改动了进入 edit 的素材。
- 用增强掩盖选错的 take：选片仍以原始 take 为准，增强不是补救手段。
- 声称"身份保持"却没有人工对比。
- 增强后音画不同步、丢音轨、改帧率，或时长漂移超过 1 帧。

---

## 3. 约束

- 遵守 `AGENT_GUIDE.md` Rule Zero：Python 只做工具与持久化，编排、取舍、审批在指令层。
- 本地优先：只走本机 ComfyUI；云端增强不在本期范围。
- 决策必须写入 `decision_log`；未选择不得发起生成。
- 目标机器：Windows 10、RTX 4070 Ti SUPER 16 GB、ComfyUI 0.45.0、OpenMontage `.venv` Python 3.11。
- ComfyUI 的模型/节点目录可能因安装方式不同而变化，所有路径必须可覆盖、可离线检查。
- `asset_manifest` 与 `decision_log` 的 schema 都是 `additionalProperties: false`，新增字段必须同步改 schema。

---

## 4. 方案比较（已选定方案 1）

### 方案 1（选定）：独立 `comfyui_enhance` 工具 + 子门禁

- 新工具位于 `tools/enhancement/comfyui_enhance.py`，`capability="enhancement"`、`provider="comfyui"`。
- 复用 `tools/_comfyui/client.py` 的提交 / 等待 / 下载 / 上传与 `bind_workflow`。
- 工作流内置到 `tools/_comfyui/workflows/`，与 HyperFlow 同构，附 provenance。
- 新增 `lib/local_enhancement_readiness.py` 与 `lib/enhancement_selection.py`。
- `cinematic.yaml` 的 `assets` 增加 `enhancement_selection` 子阶段。

**优点**：registry、provider menu、能力路由、就绪状态、决策日志、资产溯源一次做对；与已跑通的 HyperFlow 模式完全同构。
**代价**：约 600–800 行新增代码与测试。

### 方案 2（否决）：用 `comfyui_video` 的 `workflow_path`

代码最少，但 `comfyui_video` 的 capability 是 `video_generation`，增强路线永远不会出现在 `enhancement` 菜单；现有的 `bind_workflow` 只上传图片、不处理视频输入；结果"能用但不可治理"。

### 方案 3（否决）：扩展 `upscale` / `face_restore`

`face_restore` 当前就是 unavailable（GFPGAN 依赖缺失），两套模型语义混在一个工具里会让就绪检查和输入契约变复杂，且无法表达"视频超分需要先上传视频"。

---

## 5. 设计细节

### 5.1 工具契约：`comfyui_enhance`

文件：`tools/enhancement/comfyui_enhance.py`
类名：`ComfyUIEnhance`（PascalCase，无 Tool 后缀）

```python
name = "comfyui_enhance"
version = "0.1.0"
tier = ToolTier.ENHANCE
capability = "enhancement"
provider = "comfyui"
stability = ToolStability.BETA
execution_mode = ExecutionMode.SYNC
determinism = Determinism.SEEDED
runtime = ToolRuntime.LOCAL_GPU
dependencies = []                     # 服务与模型由 readiness / execute 检查
agent_skills = ["video-enhancement"]
fallback = None                      # 不静默回退到 Real-ESRGAN / GFPGAN
```

#### 输入

| 参数 | 类型 | 默认 | 适用 | 说明 |
|---|---|---|---|---|
| `operation` | enum | 必填 | 两者 | `face_refine` 或 `video_upscale` |
| `input_path` | string | 必填 | 两者 | 源视频路径 |
| `output_path` | string | 必填 | 两者 | 必须落在 `projects/<id>/` 下 |
| `reference_image_paths` | array[string] | `[]` | face_refine | **恰好 2 张**：角色面部特写 + 服装/全身参考；数量不符直接报错（工作流节点 6/7 都必需，不做单图复制） |
| `prompt` | string | 必填 | face_refine | 主体/身份描述，编译进 `MiniMaxH3ReferenceToVideo` |
| `denoise` | number | `0.4` | face_refine | 主去噪强度（关键旋钮） |
| `face_select` | enum | `largest_face` | face_refine | 传给 `H3FaceTrackCrop.select` |
| `identity_threshold` | number | `0.28` | face_refine | 身份跟踪阈值 |
| `face_denoise_multiplier` | number | `1.0` | face_refine | `H3PerFrameDenoise` 大/小脸乘数 |
| `resolution` | integer | `1080` | video_upscale | 短边目标分辨率 |
| `max_resolution` | integer | `0` | video_upscale | 0 表示不额外限制 |
| `batch_size` | integer | `5` | video_upscale | |
| `temporal_overlap` | integer | `3` | video_upscale | |
| `color_correction` | enum | `lab` | video_upscale | `lab / wavelet / none` |
| `seed` | integer | `42` | 两者 | |
| `models` | object | `{}` | 两者 | 覆盖默认模型文件名 |
| `server_url` | string | `None` | 两者 | 覆盖 `COMFYUI_ENHANCE_SERVER_URL` / `COMFYUI_SERVER_URL` |
| `timeout_seconds` | integer | `7200` | 两者 | 长任务预算 |

`models` 可覆盖的键（默认值即本机已安装版本）：

**face_refine**

```text
unet        = Minimax-h3_Singularity_ref2va_v2_int8.safetensors
clip        = qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
vae_video   = minimax_h3_video_vae_fp16.safetensors
vae_audio   = minimax_h3_audio_vae_fp32.safetensors
lora        = MiniMax-H3\加速\PikaFlex-Turbo-8步高清多模态参考视频加速.safetensors
detector    = face_yolov8n.pt
```

**video_upscale**

```text
seedvr2_dit = seedvr2_ema_3b_fp8_e4m3fn.safetensors
seedvr2_vae = ema_vae_fp16.safetensors
```

#### 输出（`ToolResult.data`）

```json
{
  "operation": "face_refine",
  "output_path": "projects/<id>/assets/video/enhanced/s1-take1-face-refine.mp4",
  "source": {"width": 640, "height": 352, "fps": 24, "duration_seconds": 7.292},
  "enhanced": {"width": 640, "height": 352, "fps": 24, "duration_seconds": 7.292},
  "provenance": {
    "workflow": "enhance_face_refine_h3_api.json",
    "workflow_hash_sha256": "…",
    "models": {"unet": "…", "lora": "…"},
    "parameters": {"denoise": 0.4, "face_select": "largest_face", "seed": 42},
    "source_asset_path": "projects/<id>/assets/video/s1-take1.mp4"
  },
  "timing": {"queue_seconds": 0.0, "execution_seconds": 0.0, "download_seconds": 0.0}
}
```

#### 行为

1. 校验 `operation`、必填项、`output_path` 必须在 `projects/` 下。
2. 用 `ComfyUIClient(capability="enhance")` 检查服务；不可达时返回 `success=False` 和明确原因，**不回退**。
3. 读取内置工作流的深拷贝，按 operation 绑定：
   - `face_refine`
     - 节点 `1.video` ← `input_path`（绝对路径；`VHS_LoadVideoPath` 支持）
     - 节点 `6.image` / `7.image` ← 上传参考图后的服务端文件名
     - 节点 `9.prompt` ← `prompt`
     - 节点 `12.lora_name` / `108.unet_name` / `109.clip_name` / `4.vae_name` / `5.vae_name` ← `models`
     - 节点 `2.detector` / `2.select` / `2.identity_threshold` ← 输入
     - 节点 `16.denoise`、`31` 乘数、`17.noise_seed` ← 输入
     - 节点 `23.frame_rate` ← **源视频 ffprobe 帧率**（不沿用实验里的硬编码 24，否则非 24 fps 源会被重定时）
     - 节点 `23.filename_prefix` ← 输出文件名（每次运行唯一）
   - `video_upscale`
     - 节点 `21.file` ← 上传源视频后的服务端文件名（`LoadVideo` 只认输入目录文件名）
     - 节点 `10.resolution` / `max_resolution` / `batch_size` / `temporal_overlap` / `seed` / `color_correction`
     - 节点 `13.model` / `14.model` ← `models`
     - 节点 `23.filename_prefix` ← 输出文件名（每次运行唯一）
4. 输出节点：`face_refine` 用 `23`（`VHS_VideoCombine`），`video_upscale` 用 `23`（`SaveVideo`）。
5. 提交 → 等待 → 从 `/view` 下载到 `output_path`。
6. 用 ffprobe 校验：文件存在、至少一条视频流、音频流数量与源一致（源有音频则输出必须有）、时长误差 ≤ 1 帧、帧率一致。
7. 用 ffmpeg 计算输入/输出的整片 SSIM，写入 `data.validation.ssim`。若平均 SSIM > 0.999，附 warning `output_virtually_unchanged`（可能是没检测到脸或增强未生效）；不因此判失败，但门禁必须展示该 warning。
8. 任一步失败返回 `success=False`，`error` 写清是服务、节点、模型、输入还是输出校验问题；不留下半成品路径。

**人脸资格不在工具内判定**：`H3FaceTrackCrop` 没有把检测到的人脸尺寸回传给调用方，OpenMontage 的 `.venv` 也没有 cv2/mediapipe。v1 由指令层负责——agent 必须先用 `frame_sampler` 抽 3 帧确认存在一张主脸（建议脸高 ≥ 120 px），并把抽帧结果带到门禁给用户看；工具只做媒体完整性校验和 no-op 警告。

#### 耗时与成本

- `estimate_cost()` 返回 `0.0`。
- `estimate_runtime()`：
  - `video_upscale`：`duration_seconds × 178`（按实测 9 分钟 / 3.04 秒折算），加 30 秒加载余量。
  - `face_refine`：实测未精确计时，v1 返回 `duration_seconds × 60 + 120` 秒，并标记 `estimate_source: "placeholder"`；首次试点后校准。
- 工具在 `data` 中回传真实 `timing`，供后续校准。

### 5.2 内置工作流与溯源

新增：

```text
tools/_comfyui/workflows/enhance_face_refine_h3_api.json
tools/_comfyui/workflows/enhance_seedvr2_3b_api.json
tools/_comfyui/workflows/ENHANCE_PROVENANCE.md
```

- 两个 JSON 从 `projects/_h3-api-export/` 的 API 版本复制，去机器化：
  - 源视频路径改为空字符串占位（运行时必绑）。
  - 参考图文件名改为空字符串占位（运行时必传）。
  - `filename_prefix` 改为 `om_enhance/<operation>`（运行时按输出名覆盖）。
  - 模型文件名保留为默认值，文档注明"本机安装版本"，可通过 `models` 覆盖。
- `ENHANCE_PROVENANCE.md` 记录：来源自定义节点与示例工作流、转换方式（ComfyUI 前端导出 API 格式）、本机补丁、文件哈希、许可提示（H3 权重受 MiniMax H3 Community License 约束；SeedVR2 权重按其仓库许可）。

### 5.3 就绪检查：`lib/local_enhancement_readiness.py`

```python
check_enhancement_readiness(
    comfyui_root: str | Path,
    model_roots: Sequence[str | Path],
    *,
    server_running: bool,
    models: Mapping[str, str] | None = None,   # 覆盖默认文件名
) -> dict
```

返回：

```json
{
  "ready": false,
  "server_running": false,
  "comfyui_version": "0.45.0",
  "checks": {"comfyui_version": {...}, "custom_node:ComfyUI-H3-FaceRefine": {...}, "face_refine.unet": {...}},
  "blockers": ["ComfyUI server is not running", "…"],
  "warnings": ["SeedVR2 3B DiT missing; first run downloads ~3.16 GB"],
  "routes": {
    "face_refine": {"ready": true, "blockers": [], "warnings": [], "models": {...}},
    "video_upscale": {"ready": true, "blockers": [], "warnings": [...]}
  },
  "ready_routes": ["face_refine", "video_upscale"]
}
```

检查项：

**公共**

- ComfyUI 版本文件与最低版本（沿用 `0.43.0`）。
- `server_running`：由调用方探测，本函数不发网络请求。

**face_refine**

- 自定义节点目录（缺失为 blocker，目录名大小写不敏感匹配）：
  - `ComfyUI-H3-FaceRefine`
  - `comfyui-videohelpersuite`（工作流使用 `VHS_LoadVideoPath` / `VHS_VideoCombine`）
- 模型（缺失均为 blocker）：UNET、CLIP、video VAE、audio VAE、LoRA、face detector（`face_yolov8n.pt`，通常在 `models/ultralytics/bbox/`）。
- `models/insightface/` 缺失 → **warning**（`identity_model="insightface"` 会退化身份跟踪，但不阻止运行）。
- 参考图与主体描述由运行时输入提供，不在就绪检查内。

**video_upscale**

- 自定义节点目录：`seedvr2_videoupscaler`（大小写不敏感）。
- `LoadVideo` / `GetVideoComponents` / `CreateVideo` / `SaveVideo` 是 ComfyUI 内置节点，由最低版本检查覆盖。
- DiT `seedvr2_ema_3b_fp8_e4m3fn.safetensors` 缺失 → **warning**（节点首次运行会自动下载约 3.16 GB），不是 blocker。
- VAE `ema_vae_fp16.safetensors` 缺失 → **blocker**。
- 输入视频与输出路径由运行时检查。

**语义**

- 顶层 `ready` = 服务在跑 且 至少一条路线就绪。
- `routes[*].ready` 只反映文件/节点，不反映服务；菜单组合两者。
- 菜单里不可用的路线必须保留，并写清 `rejected_because`（AGENT_GUIDE 的要求）。

### 5.4 菜单与决策：`lib/enhancement_selection.py`

固定路线（顺序即菜单顺序）：

```python
ROUTES = (
    {"route_id": "none",             "label": "不做后期增强", "tool": None},
    {"route_id": "face_refine",      "label": "H3-FaceRefine（只修最大的一张脸）", "tool": "comfyui_enhance"},
    {"route_id": "seedvr2_upscale",  "label": "SeedVR2 3B FP8（整片超分）", "tool": "comfyui_enhance"},
)
```

- `build_menu(registry, readiness, *, duration_seconds=0)`：返回每项 `{route_id, label, available, status, reason, estimated_seconds, warnings}`。
  - 工具未注册 → unavailable。
  - 路线就绪为 false 或服务未启动 → unavailable，附 blockers。
  - `none` 永远可用。
  - `estimated_seconds` 对每条路线按源片总时长计算，并注明 `estimate_source`。
- `record_selection(path, project_id, stage, route_id, options, reason)`：追加决策，`category="enhancement_selection"`、`subject="Post-enhancement route"`、`user_visible=true`、`user_approved=true`；校验 `route_id` 在 `options` 中。
- `require_selected_route(decision_log, route_id)`：与 `lib/video_model_selection.require_selected_route` 同语义；未选择或选择不一致时拒绝。
- 一次运行一条决策。选择的路线、适用的镜头范围、被拒绝的路线及原因都写进 `reason` / `options_considered`（schema 的 item 不允许额外字段，镜头子集放 `reason` 文本）。
- 决策键固定为 `(enhancement_selection, "Post-enhancement route")`，语义为 **latest-wins**：重新进入 assets 门禁补做增强时，追加一条覆盖完整当前范围的决策，旧条目保留在原始日志中（与 AGENT_GUIDE 对 `(category, subject)` 的定义一致）。不对同一运行追加多条部分范围决策。

### 5.5 流水线门禁

`pipeline_defs/cinematic.yaml` 的 `assets.sub_stages` 增加：

```yaml
- name: enhancement_selection
  description: "After takes are selected and before asset_manifest export, present the local post-enhancement menu (none / FaceRefine / SeedVR2 upscale)."
  human_approval_default: true
  tools_available: [comfyui_enhance]
  review_focus:
    - User selected a route before any enhancement ran
    - Route availability was shown with blockers, not hidden
    - FaceRefine is only applied where one dominant face exists
    - Enhanced assets keep audio, frame rate, and duration
    - asset_manifest records enhancement.source_path and parameters
```

`assets.tools_available` 和 `optional_tools` 同时加入 `comfyui_enhance`。

### 5.6 产物落点、选片一致性与资产溯源

**关键约束**：`video_compose._validate_narrative_selection` 要求 `narrative_assets.json` 中被选 take 的 `path`、`asset_manifest.metadata.narrative_selection`、assets 检查点、edit 检查点，以及每个 cut 解析后的绝对路径**完全一致**。因此不能"新增一条增强资产、让 cut 指向它"——那会触发 `Cut source does not match narrative selection`。

**做法：增强后的文件成为被选 take 的媒体路径，take 身份不变。**

- 增强产物：`projects/<project_id>/assets/video/enhanced/<shot_id>-<take_id>-<operation>.mp4`
- `lib/narrative_assets.py` 新增方法：

  ```python
  apply_enhancement(
      shot_id: str,
      take_id: str,
      path: str,                       # 增强后的媒体（项目相对路径）
      *,
      duration_seconds: float,         # ffprobe 实测
      enhancement: dict,               # operation / model / source_path / parameters / workflow_hash_sha256
  ) -> None
  ```

  - 只允许作用于**已选中**的 take，否则报错。
  - 首次增强时把原路径记入 `take["metadata"]["original_path"]`；再次增强不覆盖它，保留最初来源。
  - 更新 `take["path"]` 为增强产物；写入 `take["metadata"]["enhancement"]`。
  - 保留原有的 `seed` / `prompt` / `model` / `provider` 生成溯源字段，不覆盖。

- `NarrativeAssets.asset_manifest()` 在 take 条目上附带可选的 `enhancement` 对象（schema 见 5.7）；take 的 id 仍是 `take:<shot>:<take>`，选片结果不变，`video_compose` 的守卫无需改动。
- 增强后必须重新生成 `edit_decisions`（`NarrativeAssets.edit_decisions()` 会从更新后的 take 路径生成 cut），重新写 assets / edit 检查点，并重新走一次 edit 检查点；否则守卫会因路径不一致而拒绝渲染。
- 原始 take 文件不删除，路径保留在 `take.metadata.original_path`，供对比与回退；回退时把 `take["path"]` 改回该值并清掉 `enhancement`。
- `edit_decisions.metadata.compose_target`：若选择了 `seedvr2_upscale`，必须同步提升到增强后的分辨率（详见 5.8 的 edit-director 规则）；否则 1080 源会被重新压回 640×352，"提升分辨率"的验收不成立。

### 5.7 Schema 变更

1. `schemas/artifacts/decision_log.schema.json`
   - `category` enum 增加 `"enhancement_selection"`。
2. `schemas/artifacts/asset_manifest.schema.json`
   - asset item 增加可选 `enhancement` 对象（`additionalProperties: false`）：

     ```json
     "enhancement": {
       "type": "object",
       "required": ["operation", "model", "source_path"],
       "properties": {
         "operation": {"enum": ["face_refine", "video_upscale"]},
         "model": {"type": "string"},
         "source_path": {"type": "string", "description": "Pre-enhancement take path (project-relative)"},
         "parameters": {"type": "object"},
         "workflow_hash_sha256": {"type": "string"}
       },
       "additionalProperties": false
     }
     ```

   不新增 `derived_from`：take id 保持不变，增强只是替换了该 take 的媒体路径，源路径在 `enhancement.source_path` 里。
3. `schemas/artifacts/edit_decisions.schema.json`
   - 不新增字段；`cuts[].source` 已可指向任意路径，`metadata.compose_target` 已是既有元数据键。

### 5.8 技能与导演指令

**新增两个技能（Layer 3 + Layer 2）**

`tests/contracts/test_agent_skill_pointers.py` 要求 `agent_skills` 指向 `.agents/skills/<name>/SKILL.md` 或 `.agents/skills/<name>.md`，因此：

- 新增 `.agents/skills/video-enhancement/SKILL.md`（Layer 3，工具调用前的必读）：FaceRefine 与 SeedVR2 的节点、参数、输入绑定、失败模式、实测数据。
- 新增 `skills/creative/video-enhancement.md`（Layer 2，流水线如何用）：选择规则、门禁流程、验收与禁止事项。

**新增 `skills/creative/video-enhancement.md`**

内容：

- 两条本机路线与实测对比（读 `projects/_h3-api-export/STATUS.md` 的证据、耗时、身份/锐度结论）。
- 选择规则：
  - 单主角、脸占画面足够大（建议脸高 ≥ 120 px）→ FaceRefine。
  - 群像、远景、小脸、或需要整体细节 → SeedVR2 超分。
  - 两者都不选也是合法选择。
  - 不用增强补救选错的 take。
- FaceRefine 的"最大脸"限制：多角色同框只会修最大的一张脸，其余保持原样；必须向用户说明。
- SeedVR2 的时间成本（约 3 分钟 / 每秒视频），要求菜单展示预估并允许只对部分镜头跑。
- 输出验收：音轨、帧率、时长、身份对比、几何/背景稳定性。
- 禁止事项：静默运行、改身份不告知、把增强写进 `render_runtime` 或当成调色。

**修改导演技能**

- `skills/pipelines/cinematic/asset-director.md`
  - 在 9（Selection）之后新增 10（Post-enhancement gate）：展示菜单、记录决策、按选中 take 运行、重写 `asset_manifest`、资产门禁重新审批。
  - **FaceRefine 的参考图来源**：只从已批准的 `assets/references/characters/<character>/` 取**恰好 2 张**——面部特写 + 服装/全身。门禁要逐镜头指定"主角角色"；没有批准的角色表、或群像中没有明确主角时，该镜头不提供 FaceRefine（可改选 SeedVR2 或 none）。来源没有角色资产的项目（source-led）默认不提供 FaceRefine。
  - **主体描述**：由 agent 依据已批准的角色描述 + 镜头上下文撰写完整 `subject_definitions` 段落，随 take 的 enhancement 元数据落盘；不把实验里的翠竹描述复用给其他角色。
  - **资格预检**：运行前用 `frame_sampler` 抽 3 帧，确认有一张主脸（建议脸高 ≥ 120 px），抽帧图随门禁展示；工具不判脸。
  - **重入流程**：增强后调用 `NarrativeAssets.apply_enhancement`，重新导出 `asset_manifest`、重新生成 `edit_decisions`、重写 assets 检查点并再次审批。
- `skills/pipelines/cinematic/edit-director.md`
  - 切点由更新后的 take 路径重新生成，指向增强后的媒体；`reason` 注明该 take 已增强。
  - **若选择了 `seedvr2_upscale`，必须把 `edit_decisions.metadata.compose_target` 提升到增强后的分辨率**（短边 1080、按源宽高比推导、偶数取整）；保持 640×352 会把超分结果重新压回去，视为验收失败。若用户明确要求保留原交付分辨率，则本次不跑超分。
  - Cleanup pass 不得重复或抵消增强；不要为了"统一"再次锐化/降噪。
- `skills/pipelines/cinematic/compose-director.md`
  - 说明增强是上游步骤；compose 不得静默再增强或替换渲染路径。
  - 若增强存在，渲染前核对 `compose_target` 与增强分辨率一致，并在 `render_report` 里记录。
- `skills/pipelines/cinematic/proposal-director.md`
  - 在制作计划里提一句：增强在 assets 阶段由用户选择，本地零成本、只耗时间；不在 proposal 锁定。
- `skills/creative/video-model-selection.md`
  - 在"生成后"段落交叉引用 `video-enhancement.md`。

### 5.9 失败与回退

- ComfyUI 未启动 / 不可达 → 工具返回明确错误；菜单在就绪阶段即显示 unavailable；不自动启动 ComfyUI（那是 comfy-mcp 的职责，不在本工具范围内）。
- 节点缺失 → blocker，提示安装哪个 custom node pack。
- 模型缺失（FaceRefine）→ blocker，列出缺失文件名与搜索根目录。
- SeedVR2 DiT 缺失 → warning + 首次下载提示；实际运行失败则返回节点错误原文。
- 输出校验失败 → 不覆盖已有文件；保留 ComfyUI 服务端输出用于排查，并把路径写进错误信息。
- 输出几乎无变化（SSIM > 0.999）→ 返回成功但附 `output_virtually_unchanged` warning；门禁必须展示，由用户决定接受、换镜头或改选路线。
- 人脸不够大 / 找不到主脸 → 指令层在运行前拦截；工具侧没有检测能力，文档与门禁必须说清这一限制。
- 用户拒绝增强 → 记录 `selected="none"` 的决策，流程继续。
- 不提供任何自动兜底（Real-ESRGAN / GFPGAN / FFmpeg 滤镜）。
- **决策强制在指令层**：`comfyui_enhance` 不接受 decision_log 参数，也不自查选择——与现有生成工具一致，由 asset-director 调用 `require_selected_route` 保证。其他流水线能发现该工具，但只有 `cinematic` 有门禁；这是已知边界，写进技能文档。

---

## 6. 测试与验收

### 单元测试

1. `tests/lib/test_local_enhancement_readiness.py`
   - 全齐 → `ready`，两条路线都就绪。
   - 缺 FaceRefine 节点或 `comfyui-videohelpersuite` → 该路线 blocker，另一条不受影响。
   - 缺 UNET/CLIP/LoRA/detector → 各自 blocker。
   - 缺 `insightface` 模型 → warning，路线仍就绪。
   - 节点目录大小写不同（如 `comfyui-videohelpersuite`）→ 仍识别为已安装。
   - 缺 SeedVR2 DiT → warning，`ready` 仍可为 true。
   - 缺 SeedVR2 VAE → blocker。
   - 服务未启动 → 顶层 blocker，但 `routes` 仍反映文件状态。
   - 旧 ComfyUI 版本 → blocker。
2. `tests/lib/test_enhancement_selection.py`
   - 菜单包含三条路线且顺序固定。
   - 工具未注册 / 路线未就绪 / 服务未启动 → unavailable 且带原因。
   - `none` 永远可用。
   - `record_selection` 写入合法决策，`require_selected_route` 能通过/拒绝。
   - 决策能通过 `decision_log.schema.json` 校验。
3. `tests/tools/test_comfyui_enhance.py`（注入伪 client，不连真服务）
   - 未知 operation → 失败。
   - `face_refine` 参考图不是恰好 2 张、或缺 prompt → 失败。
   - `output_path` 不在 `projects/` 下 → 失败。
   - FaceRefine 绑定命中正确节点（1/6/7/9/12/108/109/4/5/16/31/17/23），且 `23.frame_rate` 取源 fps 而不是 24。
   - SeedVR2 绑定命中正确节点（21/10/13/14/23），并上传源视频。
   - 服务不可达 → 明确错误，不回退。
   - 下载后 ffprobe 校验失败（模拟无音轨）→ 失败并说明。
   - SSIM 接近 1 时输出 `output_virtually_unchanged` warning，但 `success=True`。
4. `tests/lib/test_narrative_enhancement.py`
   - `apply_enhancement` 只接受已选中 take。
   - 首次增强写入 `original_path`，再次增强不覆盖它。
   - `asset_manifest()` 的 take 条目携带 `enhancement` 对象。
   - 增强后 `edit_decisions()` 的 cut 指向增强路径。
   - 构造临时项目（catalog + manifest + assets/edit 检查点）后，`video_compose._validate_narrative_selection` 通过；把原始 take 路径改回去则拒绝。
   - 回退（恢复 `original_path` 并清掉 `enhancement`）后守卫仍通过。
5. `tests/contracts/test_video_enhancement_integration.py`
   - `cinematic.yaml` 含 `enhancement_selection` 子阶段与 `comfyui_enhance`。
   - `asset-director.md` 同时引用 `video-enhancement.md` 与 `.agents/skills/video-enhancement/`。
   - `.agents/skills/video-enhancement/SKILL.md` 存在（覆盖 `test_agent_skill_pointers`）。
   - `decision_log.schema.json` 含 `enhancement_selection`。
   - `asset_manifest.schema.json` 允许 `enhancement` 对象。
   - 两个内置工作流文件存在且是 API 格式（节点值为 dict、含 `class_type`）。

### 契约回归

- 现有 `tests/lib/test_local_video_readiness.py`、`tests/lib/test_video_model_selection.py`、`tests/lib/test_local_h3_variants.py`、`tests/contracts/test_hell_grind_integration.py` 必须继续通过。
- `pipeline_defs` schema 校验通过。

### 运行验收（Operational）

1. **SeedVR2 工具路径**：对 `projects/hyperflow-pilot` 至少一条已选 take 跑 `video_upscale`，确认输出短边 1080、音轨保留、帧率不变、时长误差 ≤ 1 帧、SSIM 有实际变化。
2. **FaceRefine 工具路径**：试点没有已批准的三联角色表，不能直接跑 FaceRefine。用 `_h3-api-export` 的 smoke 源片 + 它的两张参考图验证工具路径（可播放、音画同步、身份可人工比对）；在试点里，只有存在批准角色表的镜头才提供 FaceRefine。
3. **选片一致性**：对增强后的 take 调用 `apply_enhancement`，重新导出 `asset_manifest`、重新生成 `edit_decisions`、重写 assets/edit 检查点；确认 `video_compose` 的叙事选片守卫通过，没有被 `Cut source does not match narrative selection` 拒绝。
4. **合成提升**：把 `edit_decisions.metadata.compose_target` 提升到增强分辨率，重跑 compose，确认成片分辨率实际提升、`render_runtime="ffmpeg"` 未变。
5. **记录**：实测耗时、显存、质量结论写到 `docs/superpowers/plans/artifacts/2026-11-21-enhancement-pilot.md`。
6. 若 FaceRefine 的身份漂移不可接受，技能文档必须写清并建议群像/远景只用 SeedVR2。

---

## 7. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | SeedVR2 约 3 分钟/秒视频，20 秒 take 约 1 小时 | 菜单显示预估；允许只对部分镜头跑；支持 `timeout_seconds` |
| R2 | FaceRefine 身份漂移 | 只用单主角、足够大的脸；提供身份参考；强制人工对比 |
| R3 | 多角色镜头只修最大脸 | 菜单标签与技能文档双重说明；群像默认走 SeedVR2 |
| R4 | 模型文件名因安装而异 | `models` 覆盖 + 就绪检查报告实际搜索路径 |
| R5 | SeedVR2 首次运行自动下载 3.16 GB | 作为 warning 显式展示；不静默阻塞 |
| R6 | ComfyUI 视频上传依赖 `/upload/image` 接受非图片文件 | 新增通用上传方法并加测试；失败时错误可读 |
| R7 | 增强产物分辨率变化导致 compose 行为变化 | 选择 upscale 时强制同步提升 `compose_target`；compose 前用 ffprobe 校验；edit 的 `fps` 保持不变 |
| R8 | 决策日志 item 禁止额外字段，镜头子集无处结构化存放 | 写进 `reason` 文本；不擅自扩 schema |
| R9 | 增强路径与 `narrative_selection` 守卫不一致 | 增强只改被选 take 的 `path`，不改 take id；重新生成 edit_decisions 与检查点；新增守卫回归测试 |
| R10 | FaceRefine 找不到脸时输出近似不变却报成功 | 工具计算 SSIM 并在 > 0.999 时给 `output_virtually_unchanged` warning；门禁展示；运行前由 agent 抽帧确认主脸 |
| R11 | 非 24 fps 源被工作流硬编码重定时 | 绑定 `23.frame_rate` 到源 fps，并用测试覆盖 |
| R12 | 新工具被其他流水线发现后绕过门禁使用 | 技能文档写明这是 `cinematic` 的门禁；工具本身不查决策，与现有生成工具一致 |

---

## 8. 实施顺序（高层）

1. schema（decision_log / asset_manifest）+ 契约测试。
2. `lib/local_enhancement_readiness.py` + 测试。
3. 内置工作流清洗与 provenance。
4. `lib/narrative_assets.py` 的 `apply_enhancement` + `asset_manifest` 输出扩展 + 守卫回归测试。
5. `tools/enhancement/comfyui_enhance.py` + 单元测试（伪 client、SSIM warning、帧率绑定）。
6. `lib/enhancement_selection.py` + 测试。
7. `.agents/skills/video-enhancement/SKILL.md` + `skills/creative/video-enhancement.md`。
8. `cinematic.yaml` 子门禁 + 导演技能 + 契约测试。
9. 运行验收：试点 take 超分、smoke 片修脸、重跑 edit/compose、记录报告。

---

## 9. 留给 builder 的决定

- 视频上传用新增的通用方法还是复用 `upload_image`（建议新增 `upload_input_file`，避免把视频塞进 `files={"image": ...}` 的语义）。
- 输出校验的具体容差实现（1 帧 vs 固定毫秒）。
- 伪 client 的注入方式（构造参数 vs monkeypatch）。
- 就绪检查中模型文件名大小写不敏感的匹配细节。
- 是否把 `comfyui_enhance` 加入 `provider_menu_summary()` 的 enhancement 家族展示（取决于 registry 现有聚合逻辑）。

已裁决、不再留给 builder：FaceRefine 必须恰好 2 张参考图；`prompt` 由调用方传完整 `subject_definitions` 段落；人脸资格由指令层抽帧判断；决策强制在指令层；决策 latest-wins；增强通过替换被选 take 的 `path` 实现。

---

## 10. 评审问题的裁决（2026-11-21）

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 增强资产如何满足 `narrative_selection` 守卫 | 不新增资产条目；`apply_enhancement` 把被选 take 的 `path` 换成增强文件，take id 不变；原路径存 `original_path`；重新生成 edit_decisions 与检查点，守卫不改 |
| 2 | 是否需要提升 `compose_target` | 是。选 `seedvr2_upscale` 时必须把 `metadata.compose_target` 提升到增强分辨率；否则不跑超分 |
| 3 | FaceRefine 的身份参考图与主体描述从哪来 | 已批准角色表的**面部特写 + 服装/全身**两张；门禁逐镜头指定主角；无批准角色表或无明确主角时不提供 FaceRefine；主体描述由 agent 依据角色描述与镜头上下文撰写并落盘 |
| 4 | `agent_skills` 指向哪里 | 新增 `.agents/skills/video-enhancement/SKILL.md`（Layer 3）；Layer 2 是 `skills/creative/video-enhancement.md` |
| 5 | 只有一张参考图时节点 7 怎么填 | 不支持一张；`face_refine` 要求恰好 2 张，否则报错 |
| 6 | 找不脸/输出无变化如何判定 | 工具只做媒体校验 + SSIM warning；运行前由 agent 抽 3 帧确认主脸，门禁展示；不引入 cv2/mediapipe |
| 7 | `23.frame_rate` 是否绑定源 fps | 是。绑定 ffprobe 帧率，不硬编码 24 |
| 8 | 决策强制在工具还是指令层 | 指令层，与现有生成工具一致；工具不接收 decision_log |
| 9 | 一次运行一条决策还是可重入 | latest-wins；重入时追加覆盖完整当前范围的决策，旧条目保留 |
| 10 | 就绪检查是否覆盖传递依赖 | 是。FaceRefine 增加 `comfyui-videohelpersuite`（blocker）与 `insightface`（warning）；SeedVR2 的 ComfyUI 内置节点由版本检查覆盖 |
