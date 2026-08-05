# Video_to_Text — 项目上下文

> Codex 新会话自动加载。最后更新：2026-08-06

---

## 项目概述

将视频转换成结构化文本的 Python 工具。三大功能：
1. **音频提取 + ASR 转录**（DashScope Paraformer 主，faster-whisper GPU 备）
2. **关键帧提取 + 场景描述**（通义千问 VL，国内直连）
3. **OCR 屏幕文字提取**（EasyOCR，中文识别好）

输出按时间轴排列的 Markdown + 全量 JSON。每个视频一个文件夹：`outputs/日期/视频名/report.{json,md}` + `keyframes/`。

## 部署架构（2026-08-06 迁移后）

```
TG → Nova (mote-home, OpenClaw :18790) → 服务器跑 pipeline → SCP 回 Mote-Office
```

| 机器 | 角色 |
|------|------|
| Mote-Office | 文件存储（`E:\Desktop\Video_to_Text\videos` + `outputs`） |
| mote-home | 处理服务器（`/mnt/data/Video_to_Text/`，conda `Video_to_Text`） |

Nova 通过 node (WebSocket over Tailscale) 操控 Mote-Office 做 SCP 传输。
视频和输出留在本机，处理在服务器，不占本机资源。

## 技术栈

| 组件 | 技术 | 备注 |
|------|------|------|
| 语言 | Python 3.12 | conda env: `Video_to_Text` |
| ASR | DashScope Paraformer (主) + faster-whisper small (备) | DashScope 快 3 倍 + 自带标点 |
| 纠错 | DeepSeek API | 修同音错别字 |
| OCR | EasyOCR (ch_sim+en) | CPU 模式，中文识别好 |
| 视觉 | 通义千问 VL (qwen-vl-max) | DashScope，国内直连 |
| 视频处理 | ffmpeg | 系统安装 (Ubuntu) / conda (Windows) |
| 配置 | Pydantic + YAML + .env | CLI > .env > config.yaml |
| 输出 | JSON + Markdown | 时间轴格式 |

## 项目结构

```
Video_to_Text/
├── main.py               # CLI 入口 + 管线编排
├── status.py              # 管线状态总览，Nova 调用
├── config.py / config.yaml  # 配置管理
├── models.py             # 共享数据类
├── audio_extractor.py    # ffmpeg 音频提取
├── transcriber.py        # ASR：DashScope Paraformer + faster-whisper
├── transcript_fixer.py   # DeepSeek 纠错后处理
├── keyframe_extractor.py # ffmpeg 关键帧（interval/scene/smart）
├── scene_describer.py    # 多 provider 场景描述
├── ocr_extractor.py      # EasyOCR + Mote Sense 远程 OCR
├── output_writer.py      # JSON + Markdown + SRT
├── content_analyzer.py   # B站 API → 自动分类 → 动态 scene prompt
├── skills/               # Nova Skill 源文件
│   ├── SKILL.md           #   OpenClaw Skill 定义
│   ├── video-pipeline.sh  #   bash 包装脚本（Linux）
│   └── video-pipeline.ps1 #   PowerShell 包装脚本（Windows，已废弃）
├── config.yaml           # 默认配置
├── .env                  # API keys（DASHSCOPE_API_KEY, DEEPSEEK_API_KEY）
├── requirements.txt
├── videos/               # 待处理视频（按日期分文件夹）
└── outputs/              # 输出结果（按日期分文件夹）
```

## Nova 服务器驱动

详见 [CLAUDE.md](CLAUDE.md) Nova 服务器驱动章节。

## 已知问题

- DeepSeek API 不支持图片输入
- Gemini 免费层配额太小不稳定
- 部分录屏视频 AAC 音频编码损坏
- pipeline_server.py 已删除（被 Nova + main.py 直接调用取代）
- stella_bridge.py 已删除
- Stella 已下线

## 使用方式

```bash
# 本机（Windows）
conda activate Video_to_Text
python main.py videos/日期文件夹/视频.mp4

# 服务器（Ubuntu）
~/miniconda3/bin/conda run -n Video_to_Text python main.py <视频路径>
bash skills/video-pipeline.sh process <视频路径>

# 常用参数
python main.py video.mp4 --skip-vision
python main.py video.mp4 --interval 30
python main.py video.mp4 --asr-engine faster-whisper --device cuda
```

## 配置优先级

CLI args > .env > config.yaml
