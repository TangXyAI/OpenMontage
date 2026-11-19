# Hell-Grind × OpenMontage 整合方案

> 状态：设计稿（v2，2026-11-19）。尚未实施。
> 目标：把 Hell-Grind 的制作方法论接入 OpenMontage 的 `cinematic` 流水线，
> 并让 Seedance 2.5、MiniMax H3 全家族及其衍生变种在生成前由用户明确选择。
>
> 源档案：`D:\AI\higgsfield-hell-grind-opensource`（只读，不入库）。

---

## 1. 设计原则

1. **只扩指令层，不加 Python 编排** —— 遵守 AGENT_GUIDE 的 Rule Zero：
   `Python = tools + persistence`。
2. **`shot_spec` 模型无关** —— 镜头规格与具体模型的 prompt 解耦，换模型不重写流程。
3. **资产先行，先审后烧** —— 角色/地点/道具资产过审后才批量生成 take。
4. **模型与路线必须由用户选择** —— 不在执行阶段静默路由或降级。
5. **档案只读** —— 不复制 925GB 媒体；只导入知识（技能/方法论）与索引（prompt/成本）。

---

## 2. 总体架构（分层）

```text
╔══════════════════════════════════════════════════════════════════════════════╗
║                    Hell-Grind → OpenMontage 整合架构                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ┌───────────────────────────┐        ┌────────────────────────────────────┐ ║
║  │ L0 只读源档案（仓库外）    │        │ OpenMontage 主仓                   │ ║
║  │ brief/  skills/  folders/ │        │                                    │ ║
║  │ meta/   zh/               │        │ L1 指令层                          │ ║
║  │                           │─提炼──▶│  skills/creative/                  │ ║
║  │ CINEDANCE / ACTING / LIRA │─导入──▶│   narrative-consistency.md   [新]  │ ║
║  │ 23,305 条 Seedance prompt │─索引──▶│   video-model-selection.md   [新]  │ ║
║  │ 26,903 条中文对照         │─索引──▶│  .agents/skills/                   │ ║
║  │ 成本 / 采纳 / 映射        │─校准──▶│   cinedance/ acting-system/        │ ║
║  └───────────────────────────┘        │   lira-image-prompts/        [新]  │ ║
║                                       │                                    │ ║
║                                       │ L2 流程层                          │ ║
║                                       │  pipeline_defs/cinematic.yaml      │ ║
║                                       │  skills/pipelines/cinematic/*      │ ║
║                                       │   └ assets 增加 model_selection 门禁│ ║
║                                       │                                    │ ║
║                                       │ L3 工具层（runtime 不变）           │ ║
║                                       │  image_selector → NBP/Seedream/GPT │ ║
║                                       │  video_selector → 发现与预检        │ ║
║                                       │  seedance_* / minimax_* / runway_* │ ║
║                                       │  atlas_video / comfyui_video       │ ║
║                                       │  h3_max_video / pika_video         │ ║
║                                       │  lib/narrative_assets.py           │ ║
║                                       │  video_compose / color_grade       │ ║
║                                       │                                    │ ║
║                                       │ L4 验收层                          │ ║
║                                       │  tests/contracts/ + pilot          │ ║
║                                       └────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 3. 核心中间层：`shot_spec`

`shot_spec` 是把 Hell-Grind 的 15 段镜头模板拆成「规格」后的模型无关产物。

```text
┌────────────────────────────────────────────────────────────────────┐
│ shot_spec                                                          │
│                                                                    │
│ 1  SCENE CONTEXT          9  ACTION TIMING                         │
│ 2  ACTIVE REFERENCES     10  PHYSICS                               │
│ 3  LOCATION MAP          11  LIGHTING                              │
│ 4  FIRST FRAME/BLOCKING  12  AUDIO                                 │
│ 5  FORMAT MODE           13  CHARACTER ACTING   ◀ ACTING           │
│ 6  OPTICS                14  STYLE PREFIX                          │
│ 7  CAMERA                15  QUALITY / POSITIVE CONSTRAINTS        │
│ 8  ...                                                             │
│                                                                    │
│ + 资产引用：descriptor_ids[] / reference_images[]                   │
│ + 视频参考：reference_video_ids[]      ◀ 视频角色卡                 │
│ + 语音参考：reference_audio_ids[]      ◀ 视频角色卡                 │
│ + 来源：scene_id / beat_id / take_budget                           │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. 视频模型与路线选择门禁（v3：本地优先）

### 4.0 本地优先策略

默认顺序：

```text
本地 ComfyUI + MiniMax H3（HyperFlow 加速）
        ↓ 不可用 / OOM / 质量不达标（需用户批准）
云端 MiniMax H3（官方 / fal / Runway / Atlas）
        ↓
Seedance 2.5（fal / Ark / Atlas）
        ↓
Pika H3 Flex
```

本地路线能给出结果时，优先本地；切云端必须走 4.2 的变更门禁，不允许静默降级。

### 4.1 支持范围

#### 4.1.0 本地 ComfyUI（首选）

| 路线 | 工具 | model_family | 说明 |
|---|---|---|---|
| H3 + HyperFlow Flash INT8 | `comfyui_video` | `minimax_h3_hyperflow_local`（新增） | 6/8 步蒸馏；t2v / i2v / flf2v / ref2v |
| H3 + HyperFlow GGUF Q4_K_M | `comfyui_video` | `minimax_h3_hyperflow_local` | 16GB 显存更稳；需要 ComfyUI-GGUF |
| H3 原版（本地权重） | `comfyui_video` | `minimax_h3_local` | 20 步；已有 hybrid / Singularity 权重 |

#### 4.1.1 Seedance 2.5

| 路线 | 工具 | 模型 / 参数 | 操作 | 5s 估算 |
|---|---|---|---|---|
| fal.ai | `seedance_video` | `model_version="2.5"` | t2v / i2v / ref | ~$1.50 |
| 火山 Ark | `seedance_ark` | `variant="2.5"` | t2v / i2v / ref | ~$0.69 |
| Atlas Cloud | `atlas_video` | `bytedance/seedance-2.5/*` | t2v / i2v / ref | ~$0.67 |

#### 4.1.2 MiniMax H3 家族（官方模型）

| 路线 | 工具 | 模型 ID | 操作 | 时长 | 分辨率 | 5s 估算 |
|---|---|---|---|---|---|---|
| 官方直连 v2 | `minimax_video` | `MiniMax-H3` | t2v / i2v / 首尾帧 / ref | 4–15s | 2K | ~$0.65 |
| fal.ai | `minimax_fal_video` | `fal-ai/minimax/hailuo-03/*` | t2v / i2v / ref | 4–15s | 2K | ~$0.95 |
| Runway | `runway_video` | `hailuo3` | t2v / i2v | 5–15s | 768P / 2K | ~$0.75 |
| Atlas Cloud | `atlas_video` | `minimax/h3/*` | t2v / i2v / ref | 4–15s | 768P / 2K | ~$0.50 |
| ComfyUI Partner Node | `comfyui_video` | `minimax_h3_api` | 内置仅 t2v | — | — | Comfy credits |
| ComfyUI 本地权重 | `comfyui_video` | `minimax_h3_local` | 自定义工作流 | — | — | ~$0 |

H3 共性：原生音频；支持参考图/视频/音频；t2v 需要显式比例（不能用 adaptive）。

#### 4.1.3 H3 衍生变种

| 变种 | 工具 | 模型 ID | 特点 | 5s 估算 |
|---|---|---|---|---|
| H3 Max（fal 后训练） | `h3_max_video` | `h3-max` | 480P / 768P / 1080P，原生音频 | 需实时报价 |
| Pika H3 Flex | `pika_video` | `pika-h3-flex` | 3–15s，480p/768p 原生，最高 4K 上采样，12 参考 | ~$0.12 |

#### 4.1.4 HyperFlow（本地 H3 加速变种）

HyperFlow 是 Video Rebirth 为 MiniMax-H3 发布的少步蒸馏权重（官方 4/6/8 步，CFG 1.0），
ComfyUI 上有两套实现：

| 实现 | 节点包 | 加载器 | 步数 | 特点 |
|---|---|---|---|---|
| 官方 HyperFlow Flash | `comfyui-hyperflow-flash` | `HyperFlowLoader` / `HyperFlowGGUFLoader` + `HyperFlowSigmas` | 4 / 6 / 8 | INT8 safetensors 或 GGUF Q4_K_M |
| HyperFlow INT8 社区版 | `comfyui-hyperflow-int8-nodes` | `HyperFlowINT8Loader` | 6 | 只走 INT8；提供 5 个现成工作流 |

**操作覆盖**

| 变体 | 权重 | 支持 |
|---|---|---|
| `fl2va`（INT8） | `minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors` | t2v / i2v / 首尾帧 |
| `ref2va`（INT8） | `minimax_h3_ref2va_hyperflow_flash_14b-int8_convrot.safetensors` | 参考图/视频/音频 → 视频 |
| `fl2va`（GGUF） | `minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf` | t2v / i2v / 首尾帧 |
| `ref2va`（GGUF） | `minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf` | reference → video |

**依赖**

- ComfyUI ≥ 0.43.0（本机 0.45.0 ✅）
- 文本编码器 `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`（✅ 已有）
- 视频 VAE `minimax_h3_video_vae_fp16.safetensors`（✅ 已有）
- 音频 VAE `minimax_h3_audio_vae_fp32.safetensors`（✅ 已有）
- HyperFlow 检查点（❌ 未安装）
- INT8 快速工作流额外需要 `minimax_h3_sol_vae_int8_convrot.safetensors`（❌ 未安装）

**约束**

- 官方 INT8 包在 RTX 5090 上报告峰值显存 24.2 GB；本机 RTX 4070 Ti SUPER 为 16 GB，
  INT8 全分辨率可能 OOM。优先用 GGUF Q4_K_M + `--fast-disk` + 降低分辨率/帧数；
  首次必须只跑一条 5 秒测试，确认不爆显存后再批量。
- 权重属于 MiniMax-H3 的 Model Derivative，适用 MiniMax H3 Community License；
  在欧盟、英国、韩国、美国使用需 MiniMax 授权。菜单必须展示该许可提示。
- 工作流必须以 **API 格式**（`class_type`）交给 `comfyui_video`，UI 格式的 `nodes/links`
  不能直接执行；需要导出或转换。

排除项：`minimax_video` 内的 Hailuo 2.3 / 02 / T2V-01 属于 v1 家族；
`jimeng_video` 是 Hailuo/Jimeng 3.0 Pro，均不归入 H3。

> 本机当前 registry 查询：以上路线全部 `UNAVAILABLE`（未配置密钥、ComfyUI 未启动）。
> 菜单必须展示不可用状态与对应配置入口，而不是执行时才报错。

### 4.2 两级门禁

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 第一级 · proposal                                                    │
│   展示「家族 × 路线」短名单：能力、限制、成本、推荐理由              │
│   → 用户选定：模型家族 + 首选路线 + 备选路线                        │
│   → 写入 decision_log                                                │
│      category: provider_selection                                    │
│      subject:  Video model and route                                 │
├──────────────────────────────────────────────────────────────────────┤
│ 第二级 · assets（首次付费生成之前）                                  │
│   展示具体批次参数：模型 ID、分辨率、时长、take 数、单条/总成本      │
│   → 用户确认后才开始批量生成                                        │
│   → 追加同 category + subject 的新 decision_log 条目                 │
├──────────────────────────────────────────────────────────────────────┤
│ 运行中变更                                                           │
│   换模型 / 换路线 / 换分辨率档 / 跨家族草稿转定稿                    │
│   → 必须先征求同意，并追加新决定；禁止静默替换                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.3 菜单呈现

数值由各工具的 `estimate_cost` 实时生成，不写死在技能里。

```text
视频模型 · 5 秒示例（本地优先）

A. 本地 ComfyUI（首选）
   A1  HyperFlow Flash INT8    $0     6 步 · t2v/i2v/flf2v/ref2v    首选（需下载检查点）
   A2  HyperFlow GGUF Q4_K_M   $0     6/8 步 · 16GB 显存更稳          显存不足时选
   A3  H3 原版本地权重          $0     20 步 · 已有 hybrid/Singularity 质量对照

B. 云端 MiniMax H3
   B1  官方直连 MiniMax-H3     $0.65   2K · 4–15s · 中国区可切换     本地不可用时
   B2  fal hailuo-03           $0.95   2K · t2v/i2v/ref             备选
   B3  Runway hailuo3          $0.75   768P/2K · 5–15s              备选
   B4  Atlas minimax/h3        $0.50   768P/2K · 4–15s              云端低成本
   B5  ComfyUI Partner Node    credits 仅内置 t2v                   不推荐

C. H3 衍生
   C1  H3 Max (fal)            实时报价 480P/768P/1080P · 原生音频   草稿→定稿
   C2  Pika H3 Flex            $0.12   3–15s · 480p/768p · 12 参考   草稿

D. Seedance 2.5（非 H3 家族）
   D1  fal seedance_video      $1.50   15s · 原生音频 · 12 参考     需要非 H3 质感时
   D2  Ark seedance_ark        $0.69   原生音频 · 本地文件           低成本备选
   D3  Atlas                   $0.67   多模型网关                    备选
```

### 4.4 草稿与定稿策略

| 场景 | 策略 |
|---|---|
| 本地草稿 → 本地定稿 | 首选：HyperFlow 低分辨率/6 步草稿 → 同权重 8 步/高分辨率定稿 |
| 同家族降分辨率 | 允许：H3 Max 480P → 1080P；Pika 480p → 768p；Seedance 480p → 720p |
| 同模型换路线 | 允许，但记录新的 decision（路线变更，不算换模型） |
| 本地 → 云端 | 必须先征求同意并记录；观感和质感可能变化 |
| 跨家族草稿→定稿 | 必须先征求同意并记录，否则观感会对不上 |
| 官方 MiniMax-H3 仅 2K | 没有同族低价草稿；草稿走 Atlas/fal 的 768P 路线（同一模型） |

### 4.5 编译器映射

```text
shot_spec（模型无关）
        │
        ├──▶ CINEDANCE V4 ──────▶ seedance_video / seedance_ark / atlas_video
        ├──▶ minimax-h3 编译 ───▶ minimax_video / minimax_fal_video / runway_video
        │                        atlas_video / comfyui_video / h3_max_video
        └──▶ pika-h3-flex 编译 ─▶ pika_video
```

编译器在提交前校验路由约束：时长上限、分辨率、参考数量、音频支持、
比例合法性。错误在本地暴露，不留给 provider。

### 4.6 本地 ComfyUI 就绪矩阵（当前机器）

| 项 | 状态 | 说明 |
|---|---|---|
| ComfyUI 版本 | ✅ 0.45.0 | 需 ≥ 0.43.0 才原生支持 H3 |
| 工作区 | `G:\ComfyUI\Installs\ComfyUI\ComfyUI` | 服务当前**未运行** |
| GPU | RTX 4070 Ti SUPER / 16 GB | INT8 全分辨率可能 OOM |
| 磁盘 | G: 剩余约 146 GB | 足够放一个 HyperFlow 检查点 |
| HyperFlow 节点包 | ✅ 已安装 | `comfyui-hyperflow-flash`、`comfyui-hyperflow-int8-nodes` |
| HyperFlow 工作流 | ✅ 已有 | `G:\ComfyUI\Shared\workflows\MiniMaxH3\Hyperflow\`（UI 格式，需转 API 格式） |
| 文本编码器 | ✅ 已有 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| 视频 VAE | ✅ 已有 | `minimax_h3_video_vae_fp16.safetensors` 等 |
| 音频 VAE | ✅ 已有 | `minimax_h3_audio_vae_fp32.safetensors` |
| HyperFlow 检查点 | ❌ 缺失 | `fl2va` / `ref2va` 的 INT8 或 GGUF |
| sol VAE（fast 工作流） | ❌ 缺失 | `minimax_h3_sol_vae_int8_convrot.safetensors` |
| 现有 H3 权重 | ✅ 已有 | `hybrid_b25-49-int8`、`Singularity_ref2va_v2_int8` 等 |

本地路线启动前必须先通过这张表；缺失项在菜单里标红，并给出下载/安装入口。

### 4.7 本地 H3 / HyperFlow 安装与验证计划

> 目标：在本机跑通 1 条 5 秒 H3 片段（含音频），再进入批量。
> 当前：节点包、文本编码器、视频/音频 VAE 已就绪；HyperFlow 检查点与 sol VAE 缺失；ComfyUI 服务未启动。

#### 4.7.1 下载源（ModelScope 优先）

大文件一律先走 ModelScope；HuggingFace 只作兜底（本机 `HF_ENDPOINT` 已是 `https://hf-mirror.com`）。

| 文件 | 大小 | ModelScope 仓库 | 放置 | 状态 |
|---|---|---|---|---|
| `fl2va_gguf/minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf` | 9.05 GB | `VideoRebirthAI/hyperflow-h3-flash` | `G:\ComfyUI\Shared\models\diffusion_models\` | 待下载 |
| `ref2va_gguf/minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf` | 9.22 GB | 同上 | 同上 | 待下载 |
| `vae/minimax_h3_sol_vae_int8_convrot.safetensors` | 1.99 GB | `Comfy-Org/MiniMax-H3` | `G:\ComfyUI\Shared\models\vae\` | 待下载 |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 15.7 GB | `Comfy-Org/MiniMax-H3` | 已有 | ✅ |
| `minimax_h3_video_vae_fp16.safetensors` | 5.21 GB | 同上 | 已有 | ✅ |
| `minimax_h3_audio_vae_fp32.safetensors` | 0.61 GB | 同上 | 已有 | ✅ |
| ComfyUI-GGUF | — | city96（GitHub） | `custom_nodes/` | ✅ |

INT8 备选（显存充足时；两个检查点合计 32.44 GB，加 sol VAE 约 34.4 GB）：

| 文件 | 大小 | ModelScope 仓库 | 放置 | 状态 |
|---|---|---|---|---|
| `fl2va_int8_convrot_comfyui/minimax_h3_fl2va_hyperflow_flash_14b-int8_convrot.safetensors` | 16.01 GB | `VideoRebirthAI/hyperflow-h3-flash` | `diffusion_models/` | 待下载 |
| `ref2va_int8_convrot_comfyui/minimax_h3_ref2va_hyperflow_flash_14b-int8_convrot.safetensors` | 16.43 GB | 同上 | 同上 | 待下载 |

低显存备选：`Q3_K_M` 为 7.22 / 7.35 GB。

ModelScope 下载命令：

```bash
pip install modelscope

modelscope download --model VideoRebirthAI/hyperflow-h3-flash \
  --include 'fl2va_gguf/minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf' \
  --local_dir G:/ComfyUI/Shared/downloads/hyperflow

modelscope download --model VideoRebirthAI/hyperflow-h3-flash \
  --include 'ref2va_gguf/minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf' \
  --local_dir G:/ComfyUI/Shared/downloads/hyperflow

modelscope download --model Comfy-Org/MiniMax-H3 \
  --include 'vae/minimax_h3_sol_vae_int8_convrot.safetensors' \
  --local_dir G:/ComfyUI/Shared/downloads/hyperflow
```

下载完成后把文件移到 4.7.1 的目标目录；`diffusion_models/` 下直接放文件，不要保留子目录。

API 工作流是小文件，ModelScope 未托管，从 GitHub / HuggingFace 取即可。

#### 4.7.2 安装路线

**A. GGUF Q4_K_M（推荐，16 GB 显存）**

1. 下载两个 Q4_K_M GGUF + sol VAE（ModelScope，合计约 20.3 GB）
2. 用 `comfyui-hyperflow-flash` 的 `HyperFlowGGUFLoader`
3. 启动参数加 `--fast-disk`

**B. INT8（速度优先，显存充足时）**

1. 下载两个 INT8 comfyui 检查点 + sol VAE（ModelScope，合计约 34.4 GB）
2. 用 `HyperFlowINT8Loader`
3. 首次只跑 5 秒 768P 测试，确认峰值显存

#### 4.7.3 工作流接入

- **首选**：BennyDaBall 仓库的 `workflows/api/*.json`（已是 API 格式；ModelScope 未托管，从 GitHub/HF 取）
- 若用官方包工作流（只有 UI 格式）：ComfyUI 开启 Dev mode → Export (API)
- 保存到 `tools/_comfyui/workflows/hyperflow_*.json`，记录 `output_node`
- 在 `comfyui_video` 里新增 `model_family="minimax_h3_hyperflow_local"`，
  绑定 prompt / 参考图 / 种子 / 宽高 / 帧数 / 步数

#### 4.7.4 启动与冒烟

1. 启动 ComfyUI，确认 H3 / HyperFlow 节点加载无报错
2. 跑 1 条 5 秒、768P、带音频
3. 记录：耗时、峰值显存、输出文件、音频轨、节点缺失
4. 通过后写 `decision_log`：本地 HyperFlow 路线可用

验收：

- 5 秒片段完整、音画同步
- 峰值显存 < 16 GB
- `comfyui_video` 返回 success 与 timing
- 失败处理：降分辨率/帧数 → 改 GGUF → 云端（需用户批准）

#### 4.7.5 许可

HyperFlow 权重适用 MiniMax H3 Community License；欧盟、英国、韩国、美国使用需 MiniMax 授权。菜单必须展示。

---

## 5. 端到端流程

```text
 research ──▶ proposal ──▶ script ──▶ scene_plan ──▶ assets ──▶ edit ──▶ compose ──▶ publish
    │            │            │            │             │          │         │
    ▼            ▼            ▼            ▼             ▼          ▼         ▼
research_    proposal_     script      scene_plan    asset_     edit_     render_
brief        packet                    + shot_specs  manifest   decisions report
             + 模型短名单               + assets_req
             + take 预算
             + visual_identity

 ◀H▶          ◀H▶          ◀H▶          ◀H▶          ◀H▶         auto      auto      ◀H▶
```

`◀H▶` = `human_approval_default: true`。

---

## 6. `assets` 阶段内部流程

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ assets                                                                       │
│                                                                              │
│  A0 资产设计              A1 资产生成             A2 压力测试                 │
│  descriptor（文本）  ──▶  LIRA ──▶ 参考图   ──▶  身份/风格/空间/可复用       │
│  角色三联表                NBP / Seedream         失败 → 回 A0/A1            │
│  地点表 / 道具表           GPT Image 2                                       │
│         │                                                                    │
│         ▼                                                                    │
│  A2.5 空景 360° 扫描      A3 视频角色卡           A4 模型与路线门禁 ◀H▶      │
│  空景慢扫 → 补全空间  ──▶  图转视频 + 语音参考 ──▶ 家族/路线/参数/成本       │
│  解决正反打漂移                                   ↓                          │
│                                              A5 Shot Spec                    │
│                                              15 段 + ACTING 表演层           │
│                                                   ↓                          │
│                                              A6 提示词编译                   │
│                                              CINEDANCE / H3 / Pika           │
│                                                   ↓                          │
│                                              A7 批量 take                    │
│                                              ×2–4 变体/镜头                  │
│                                                   ↓                          │
│                                              A8 用户选片 ◀H▶                 │
│                                              → narrative_assets             │
│                                              → asset_manifest               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. 数据与产物落点

```text
projects/<film>/
├── artifacts/
│   ├── proposal_packet.json     # + production_mode / visual_identity / take_budget
│   │                            # + video_model_shortlist / selected_route
│   ├── script.json              # + 角色行为目标（ACTING 输入）
│   ├── scene_plan.json          # + required_assets / metadata.location_map
│   ├── shot_specs.json          # [新] 15 段模型无关规格
│   ├── narrative_assets.json    # asset / take / selection
│   ├── asset_manifest.json      # 导出最终选片
│   └── edit_decisions.json
├── assets/
│   ├── references/characters/   # 三联角色表 + 视频角色卡
│   ├── references/locations/    # 空景底图 + 360° 扫描帧
│   ├── references/props/
│   ├── images/
│   └── video/<shot_id>/<take_id>.mp4
└── renders/final.mp4
```

Schema 影响：

| Schema | 变更 | 兼容性 |
|---|---|---|
| `scene_plan.schema.json` | 用开放 `metadata` 承载 `location_map` / `style_prefix` / `take_budget` | 零改动 |
| `shot_specs` | 新增 schema | 纯新增 |
| `asset_manifest.schema.json` | 现有字段已足够 | 零改动 |
| `narrative_assets.py` | 补 `descriptor` / `character_sheet` 校验 | 小改 |

---

## 8. 技能与工具调用关系

```text
skills/creative/narrative-consistency.md   [新] 资产前置、三联角色表、压力测试
skills/creative/video-model-selection.md   [新] 模型菜单、成本口径、门禁、降级策略
        │
        ├── LIRA ──────────────▶ image_selector（NBP / Seedream / GPT Image 2）
        ├── ACTING SYSTEM ─────▶ shot_specs[].acting
        └── CINEDANCE / H3 / Pika ─▶ video_selector 发现 → 显式工具执行
```

`video_selector` 只负责发现与预检；执行阶段显式调用用户选定的工具与模型 ID，
避免打分器在用户不知情时换路。

---

## 9. 接口契约

| 组件 | 输入 | 输出 | 落盘 / 消费方 |
|---|---|---|---|
| `narrative-consistency` | `scene_plan` | 资产清单、门禁顺序、take 预算 | director 技能读取 |
| `video-model-selection` | registry 目录 | 家族/路线菜单、推荐、decision 记录 | `proposal_packet` / `decision_log` |
| LIRA | descriptor | 资产参考图 | `assets/references/**` |
| ACTING | script beat + 角色目标 | 表演规格 | `shot_specs[].acting` |
| 编译器 | `shot_spec` + 路线 | provider prompt + 参数校验 | take 的 `metadata.prompt` |
| 具体视频工具 | prompt + model + 参考 | take mp4 | `assets/video/<shot>/<take>.mp4` |
| `NarrativeAssets` | takes | catalog / manifest | `artifacts/narrative_assets.json` |

---

## 10. 检查点与审批

```text
proposal ◀H▶ script ◀H▶ scene_plan ◀H▶ assets ─┬─ A0–A2 资产表 ◀H▶
                                                ├─ A4 模型与路线 ◀H▶
                                                └─ A8 选片 ◀H▶
                                                     ↓
                                              edit ──auto──▶ compose ──auto──▶ publish ◀H▶
```

---

## 11. 实施阶段

### P0 · 知识导入与挂接（0.5–1 天）

1. 导入 3 个 Layer 3 技能：`cinedance`、`acting-system`、`lira-image-prompts`。
2. 新增 Layer 3：`hyperflow-h3`（权重、节点、步数、显存与许可说明）。
3. 新增 Layer 2：`narrative-consistency.md`、`video-model-selection.md`。
4. 挂接 `agent_skills`：Seedance 工具加 `cinedance`/`acting-system`；
   图像工具加 `lira-image-prompts`；H3/HyperFlow 工具加 `minimax-h3`/`hyperflow-h3`；
   Pika 保持 `pika-h3-flex`。
5. 更新 `cinematic.yaml` 的 `narrative_generated.agent_skills`，并把本地路线放在首位。

验收：registry 可见新技能；现有测试全绿。

### P0.5 · 本地权重准备（0.5 天，需用户批准）

- 从 **ModelScope** 下载 HyperFlow Q4_K_M（`fl2va` + `ref2va`）与 sol VAE
- 移动到 `G:\ComfyUI\Shared\models\diffusion_models\` 与 `...\vae\`
- 从 GitHub/HF 取 API 工作流，放到 `tools/_comfyui/workflows/`
- 启动 ComfyUI，跑 1 条 5 秒 768P 冒烟，记录峰值显存与耗时
- 通过后写入 `decision_log`；失败则降分辨率/帧数或改 INT8

验收：单条 5 秒片段完整、音画同步、峰值显存 < 16 GB。

### P1 · 流程固化（2–3 天）

6. `scene-director`：`scene_plan` 增加 `required_assets`、`location_map`。
7. `asset-director`：资产先行 + 空景 360° + 视频角色卡 + 模型门禁 + take 预算。
8. `proposal-director`：本地优先的模型短名单与推荐。
9. `edit/compose-director`：Cleanup / Color / Sound 映射。
10. `narrative_assets.py`：descriptor / character_sheet 校验。
11. `comfyui_video`：新增 `model_family="minimax_h3_hyperflow_local"`；
    把 HyperFlow UI 工作流转成 API 格式，绑定 prompt/图像/种子/尺寸/步数；
    启动前校验权重、节点、VAE、显存。
12. `video-selector` 菜单：本地路线置顶，显示就绪状态、步数与预计耗时。

### P2 · 语料接入（可选，0.5–1 天）

13. `reference/hell-grind/prompts.jsonl`：23,305 条 Seedance prompt + 图像 prompt 索引。
14. 中文对照索引（26,903 条），不复制媒体。
15. 许可与来源标注。

### P3 · 端到端验证（1–2 天）

16. `tests/contracts/test_video_model_selection.py`：
    菜单覆盖本地 HyperFlow、本地 H3、云端 H3、Seedance 2.5；未选择不得发起生成；
    换模型必须新增 decision。
17. `tests/contracts/test_hell_grind_integration.py`：技能、模板、门禁、schema。
18. 本地 ComfyUI 冒烟：启动服务 → 加载 HyperFlow 工作流 → 生成 1 条 5 秒测试；
    确认显存、音频、时长、节点无缺失。
19. Pilot：小场次（如 Scene 73.6，12 条）优先跑本地 HyperFlow；
    记录耗时、显存峰值、成本与一致性；质量不达标时再走云端对照。

---

## 12. 风险与待定

| # | 风险 / 决策 | 说明 |
|---|---|---|
| D1 | `shot_spec` 是否独立 sidecar | 建议是；否则 H3/Seedance 双编译器无处落地 |
| D2 | 本地 H3 首选实现 | 建议 HyperFlow Flash INT8；16GB 显存不足时改用 GGUF Q4_K_M |
| D3 | 云端 H3 备选路线 | 官方直连（2K、中国区可切换）优先；Atlas 作为低成本备选 |
| D4 | Seedance 2.5 何时使用 | 仅在需要非 H3 质感或本地/云端 H3 都不满足时 |
| D5 | 语料边界与许可 | 只导 prompt 元数据索引；媒体不入库；需标注来源 |
| D6 | 跨家族 / 本地→云端切换 | 默认禁止静默切换；必须用户确认并记录 |
| D7 | 16GB 显存风险 | INT8 全分辨率可能 OOM；先跑 5 秒单条，必要时降分辨率或换 GGUF |
| D8 | HyperFlow 权重许可 | MiniMax H3 Community License；欧盟/英国/韩国/美国需授权 |
| D9 | 工作流格式 | 现有 HyperFlow 工作流是 UI 格式，必须转成 API 格式才能交给 `comfyui_video` |

---

## 13. 验收标准

- 菜单默认把本地 ComfyUI（HyperFlow → H3 原版）放在首位，并显示就绪状态。
- 本地不可用或 OOM 时，必须停下并让用户选择云端路线，不能静默切换。
- 任意一次生成之前，`decision_log` 中存在用户确认的模型与路线记录。
- 菜单能列出本地 HyperFlow、本地 H3、云端 H3 全部路线、Seedance 2.5，并显示可用状态与成本。
- `shot_spec` 不含任何 provider 专有字段；编译器负责转换与校验。
- 切换模型/路线时，旧决定保留在 `options_considered`，新决定追加。
- 本地冒烟通过：HyperFlow 工作流生成 1 条 5 秒带音频片段，显存与节点无异常。
- Pilot 能产出完整 `shot_specs` → takes → `asset_manifest` → 成片。
