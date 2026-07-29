# Video_to_Text — 项目上下文

> Codex 新会话自动加载。最后更新：2026-07-20

---

## 项目概述

将视频转换成结构化文本的 Python 工具。三大功能：
1. **音频提取 + ASR 转录**（faster-whisper → DeepSeek 纠错别字）
2. **关键帧提取 + 场景描述**（通义千问 VL，国内直连）
3. **OCR 屏幕文字提取**（EasyOCR，中文识别好）

输出按时间轴排列的 Markdown + 全量 JSON。每个视频一个文件夹：`outputs/日期/视频名/report.{json,md}` + `keyframes/`。

## 已处理视频（31 个，全部三样齐全）

| 日期 | 数量 | 内容 |
|------|:--:|------|
| 2026-06-25 | 22 | 梗指南短视频 |
| 2026-07-01 | 8 | 股票技术分析教学（K线/均线/MACD/KDJ） |
| 2026-06-24 | 1 | Codex 财务分析（英文） |

视频按日期放入 `videos/YYYY-MM-DD/`，输出自动到 `outputs/YYYY-MM-DD/视频名/`。

## 技术栈

| 组件 | 技术 | 备注 |
|------|------|------|
| 语言 | Python 3.12 | conda env: `Video_to_Text` |
| ASR | faster-whisper small + DashScope Paraformer | CPU 模式（CUDA 环境有问题），DashScope 快 3 倍 + 自带标点 |
| 纠错 | DeepSeek API | 修 Whisper 同音错别字（军线→均线，金差→金叉） |
| OCR | EasyOCR (ch_sim+en) | 替换了 PaddleOCR（3.x 有 oneDNN bug） |
| 视觉 | 通义千问 VL (qwen-vl-max) | DashScope，国内直连，识别 K 线/均线/形态 |
| 视频处理 | ffmpeg (conda 安装) | 音频用 `-c:a pcm_s16le -err_detect ignore_err` |
| 配置 | Pydantic + YAML + .env | CLI > .env > config.yaml |
| 输出 | JSON + Markdown | 时间轴格式：画面+讲解+OCR 按时间排列 |

## 项目结构

```
Video_to_Text/
├── main.py               # CLI 入口 + 管线编排
├── pipeline_server.py     # HTTP 服务（:8940），Stella 遥控入口
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
├── stella_bridge.py      # Stella ↔ 本地管线数据桥接
├── skills/               # Stella Skill 源文件（部署到 mote-home）
│   ├── SKILL.md           #   OpenClaw Skill 定义（指令式，DeepSeek Flash 用）
│   └── analyze-video.md   #   参考文档
├── config.yaml           # 默认配置
├── .env                  # API keys（DASHSCOPE_API_KEY, DEEPSEEK_API_KEY）
├── requirements.txt
├── videos/               # 待处理视频（按日期分文件夹）
└── outputs/              # 输出结果（按日期分文件夹）
```

## Stella 遥控（企微 → 视频处理）

```
企微 → Stella (mote-home, OpenClaw) → curl :8940 → pipeline_server.py → main.py → outputs/
```

| 端点 | 用途 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /videos` | 列出所有视频 |
| `GET /status` | 任务状态 |
| `POST /process` | 处理单个视频 |
| `POST /process-batch` | 批量处理目录 |

- Skill 部署：`mote-home:~/.openclaw/workspace/skills/analyze-video/SKILL.md`
- 包装脚本：`mote-home:~/.openclaw/workspace/process-video.sh`
- 本地源文件：`skills/SKILL.md`，修改后 `scp` 到 mote-home 并重启 `openclaw-gateway`

### 🔴 DeepSeek Flash Skill 编写铁律

Flash 模型不会"读文档推断该做什么"。SKILL.md 必须：
- **祈使句**："收到后立即用 bash 执行"，不能写"命令速查"
- **✅❌ 规则**：明确禁止搜索文件、禁止犹豫
- **用包装脚本**：比裸 curl 短，减少模型犯错空间
- 改前 Stella 完全不响应，改后正常执行（2026-07-20 验证）

## 已知问题

- RTX 3050 4GB VRAM：CUDA 环境有 cublas64_12.dll 缺失问题，Whisper 目前用 CPU
- PaddleOCR 3.x 有 oneDNN bug，已换 EasyOCR
- DeepSeek API 不支持图片输入
- Gemini 免费层配额太小不稳定
- 部分录屏视频 AAC 音频编码损坏，用原始 AAC 提取策略可部分恢复
- **已解决**: Stella (DeepSeek V4 Flash) Skill 不响应 — 原因是 SKILL.md 参考文档风格，重写为指令式后正常（2026-07-20）

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
