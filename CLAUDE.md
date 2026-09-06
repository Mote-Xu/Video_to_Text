# Video_to_Text — 项目上下文

> Claude 新会话自动加载。最后更新：2026-09-07

---

## 项目概述

将视频转换成结构化文本的 Python 工具。三大功能：
1. **音频提取 + ASR 转录**（faster-whisper → ollama flash 纠错别字）
2. **关键帧提取 + 场景描述**（ollama qwen3.5 视觉）
3. **OCR 屏幕文字提取**（EasyOCR，中文识别好）

输出按时间轴排列的 Markdown + 全量 JSON。每个视频一个文件夹：`outputs/日期/视频名/report.{json,md}` + `keyframes/`。

## 已处理视频（72 个）

| 日期 | 数量 | 内容 |
|------|:--:|------|
| 2026-06-22 | 1 | 芯片设计 RISC-V |
| 2026-06-24 | 1 | Claude Code 财务分析（英文） |
| 2026-06-25 | 22 | 梗指南短视频 |
| 2026-07-01 | 7 | 股票技术分析教学（K线/均线/MACD/KDJ） |
| 2026-07-17 | 1 | 为什么网络越来越差 |
| 2026-07-20 | 38 | 社交框架合集 + 高位框架合集 |
| 2026-07-24 | 2 | Skill & Agent 自动工业化 |

视频按日期放入 `videos/YYYY-MM-DD/`，输出自动到 `outputs/YYYY-MM-DD/视频名/`。

## 技术栈

| 组件 | 技术 | 备注 |
|------|------|------|
| 语言 | Python 3.12 | conda env: `Video_to_Text` |
| ASR | faster-whisper small（本地，CPU） | 全链路 CPU：本机缺 cublas64_12.dll；服务器 torch 2.13.0 不支持 GTX 1050 Ti (sm_61)。GPU 留给 Mote Sense |
| 纠错 | ollama deepseek-v4-flash:0731 | 修 Whisper 同音错别字（军线→均线，金差→金叉） |
| OCR | EasyOCR (ch_sim+en) | 替换了 PaddleOCR（3.x 有 oneDNN bug） |
| 视觉 | ollama qwen3.5:397b | ⚠️ flash 不支持图片输入，视觉必须用 qwen3.5 |
| 视频处理 | ffmpeg (conda 安装) | 音频用 `-c:a pcm_s16le -err_detect ignore_err` |
| 配置 | Pydantic + YAML + .env | CLI > .env > config.yaml |

### 🔴 LLM 引擎：ollama cloud（2026-09-07 切换）

- **端点**：`https://ollama.com/v1`（OpenAI 兼容），key 在 `.env` 的 `OLLAMA_API_KEY`（源文件 `ollama key`，已 gitignore）
- **文本任务**（ASR 纠错 / 内容分类）→ `deepseek-v4-flash:0731`（config.yaml `ollama.model`）
- **视觉任务**（场景描述）→ `qwen3.5:397b`（config.yaml `ollama.vision_model`）——flash 不支持图片输入（HTTP 400）
- **flash 有 thinking 流**：会吃掉部分 max_tokens，纯文本任务 max_tokens 给足（≥300）
- 旧 provider（dashscope/gemini/deepseek/anthropic/openai）代码保留，改 `vision.provider` 可切回
- ⚠️ **DASHSCOPE_API_KEY 已失效**（2026-09-07 实测 401），dashscope ASR/视觉不可用
| 输出 | JSON + Markdown | 时间轴格式：画面+讲解+OCR 按时间排列 |

## 项目结构

```
Video_to_Text/
├── main.py               # CLI 入口 + 管线编排
├── status.py              # 管线状态总览（排队/完成/失败），Nova 调用
├── config.py / config.yaml  # 配置管理
├── models.py             # 共享数据类
├── audio_extractor.py    # ffmpeg 音频提取（3 策略：原始 AAC 提取优先）
├── transcriber.py        # ASR：faster-whisper + DashScope Paraformer
├── transcript_fixer.py   # DeepSeek 纠错后处理
├── keyframe_extractor.py # ffmpeg 关键帧（interval/scene/smart 三种模式）
├── scene_describer.py    # 多 provider 场景描述（dashscope/gemini/openai/anthropic）
├── ocr_extractor.py      # EasyOCR 文字提取（PIL 读取规避 OpenCV 中文路径 bug）
├── output_writer.py      # JSON + Markdown（时间轴格式） + SRT
├── content_analyzer.py   # B站 API → 自动分类视频类型 → 动态 scene prompt
├── skills/               # Nova Skill 源文件（部署到 E:\Nova\workspace\skills\）
│   ├── SKILL.md           #   OpenClaw Skill 定义（指令式，DeepSeek Flash 用）
│   └── analyze-video.md   #   参考文档
├── config.yaml           # 默认配置
├── .env                  # API keys（DASHSCOPE_API_KEY, DEEPSEEK_API_KEY）
├── requirements.txt
├── videos/               # 待处理视频（按日期分文件夹）
└── outputs/              # 输出结果（按日期分文件夹）
```

## Nova 服务器驱动（TG → 视频处理）

```
TG → Nova (mote-home, OpenClaw :18790) → python main.py video.mp4 → outputs/
```

Nova 运行在 mote-home 服务器上，直接调 `conda run -n Video_to_Text python main.py`，不需要 HTTP 中间层。
项目代码在 `/mnt/data/Video_to_Text/`（`~/Video_to_Text/` symlink）。

### 📤 输出位置与拉回规范（2026-08-30 立）

- 服务器 main.py 实际输出到**视频同目录**：`videos/日期/视频名/report.{json,md}` + `keyframes/`（旧版行为，与本地 `outputs/` 规范不同）
- **服务器不会自动同步回笔记本**——处理完后需手动 `scp -r` 拉回
- 拉回本地**必须放 `outputs/日期/视频名/`**（项目规范），❌ 禁止放 `videos/`（2026-08-30 教训：scp 目标目录写错，拉到 videos/ 造成结构错位）

### Nova Skill

- 部署位置：`/mnt/data/openclaw/nova/workspace/skills/video-to-text/SKILL.md`
- 本地源文件：`skills/SKILL.md`，修改后 `git pull` 到服务器，复制到 Nova workspace
- 包装脚本：`skills/video-pipeline.sh`（bash，Linux）
- 修改后重启 Nova gateway 生效：`sudo systemctl restart nova-gateway`

### 🔴 DeepSeek Flash Skill 编写铁律（Nova 同样适用）

Flash 模型不会"读文档推断该做什么"。SKILL.md 必须：
- **祈使句**："收到后立即用 bash 执行"，不能写"命令速查"
- **✅❌ 规则**：明确禁止搜索文件、禁止犹豫
- **用包装脚本**：比裸命令短，减少模型犯错空间
- 改前 Stella 完全不响应，改后正常执行（2026-07-20 验证）

### 与旧 Stella 方案的区别

| | Stella（已下线） | Nova 本地（已废弃） | Nova 服务器（当前） |
|---|---|---|---|
| 位置 | mote-home 远程 | Mote-Office 本地 | mote-home 本地 |
| 通信 | curl :8940 HTTP | 直接 bash 调 main.py | 直接 bash 调 main.py |
| 视频访问 | 通过 Tailscale 访问本地文件 | 本地文件系统直接读 | 服务器本地文件系统 |
| Skill | 包装脚本 curl 远程 | 直接 conda + python | bash 包装脚本 + conda |
| GPU | ❌ | ❌（CUDA DLL 缺失） | ✅ GTX 1050 Ti 4GB |

## 已知问题

- ~~RTX 3050 4GB VRAM：CUDA 环境有 cublas64_12.dll 缺失~~ **已解决：迁移到 mote-home GTX 1050 Ti，CUDA 正常工作**
- ⚠️ **ASR 全链路 CPU（刻意设计，2026-09-07 确认）**：本机缺 cublas64_12.dll；服务器 torch 2.13.0+cu130 不支持 GTX 1050 Ti (sm_61)。迁移时（08-06）ASR 走 DashScope 云端、GPU 留给 Mote Sense（mote-sense 环境 torch 2.5.1+cu121 兼容）。config.yaml `asr.device: cpu` 为默认值，Nova 驱动不传 `--device` 即可跑通
- GTX 1050 Ti 4GB VRAM：Mote Sense 专用（faster-whisper small + EasyOCR），Video_to_Text 不占用
- PaddleOCR 3.x 有 oneDNN bug，已换 EasyOCR
- DeepSeek API 不支持图片输入
- Gemini 免费层配额太小不稳定
- 部分录屏视频 AAC 音频编码损坏，用原始 AAC 提取策略可部分恢复
- **已解决**: Stella (DeepSeek V4 Flash) Skill 不响应 — 原因是 SKILL.md 参考文档风格，重写为指令式后正常（2026-07-20）
- **2026-07-26**: Stella 已下线，改由 Nova（本机 OpenClaw）直接本地驱动 main.py，去掉远程 HTTP 中间层
- **2026-08-06**: 项目从 Mote-Office 迁移到 mote-home 服务器，Nova 在服务器上直接驱动（`/mnt/data/Video_to_Text/`）
- **2026-08-06**: Nova TG bot token 缺失，需从 @BotFather 获取后更新 `/mnt/data/openclaw/nova/openclaw.json`
- **2026-09-07**: LLM 引擎切换为 ollama cloud（flash 文本 + qwen3.5 视觉）；DASHSCOPE_API_KEY 已失效（401）

## 使用方式

```bash
conda activate Video_to_Text
python main.py videos/日期文件夹/视频.mp4

# 常用参数
python main.py video.mp4 --skip-vision          # 跳过场景描述
python main.py video.mp4 --interval 30           # 30秒一帧（长视频）
python main.py video.mp4 --model small --language zh
python main.py video.mp4 --scene-mode scene --scene-threshold 0.5

# 切换视觉 API：改 config.yaml 的 vision.provider 就行
# dashscope / gemini / openai / anthropic
```

## 配置优先级

CLI args > .env > config.yaml
