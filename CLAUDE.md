# Video_to_Text — 项目上下文

> Claude 新会话自动加载。最后更新：2026-06-22

---

## 项目概述

将视频转换成结构化文本的 Python 工具。三大功能：
1. **音频提取 + ASR 转录**（faster-whisper）
2. **关键帧提取 + 场景描述**（Claude Vision API）
3. **OCR 屏幕文字提取**（PaddleOCR）

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 环境 | conda: `Video_to_Text` |
| ASR | faster-whisper (CTranslate2, GPU) |
| OCR | PaddleOCR (ch 模型) |
| 视觉 | Anthropic Claude API |
| 视频处理 | ffmpeg (subprocess) |
| 配置 | Pydantic + YAML + .env |
| 输出 | JSON + Markdown |

## 项目结构

```
Video_to_Text/
├── main.py              # CLI 入口 + 管线编排
├── config.py            # 配置管理
├── models.py            # 共享数据类
├── audio_extractor.py   # ffmpeg 音频提取
├── transcriber.py       # faster-whisper ASR
├── keyframe_extractor.py# ffmpeg 关键帧
├── scene_describer.py   # Claude API 场景描述
├── ocr_extractor.py     # PaddleOCR 文字提取
├── output_writer.py     # JSON + Markdown 输出
├── config.yaml          # 默认配置
└── requirements.txt
```

## 已知限制

- RTX 3050 4GB VRAM：Whisper 只能用 small/medium 模型
- Whisper 和 PaddleOCR 不能同时用 GPU（OCR 默认 CPU）
- Claude API 需要网络和密钥

## 配置优先级

CLI args > .env > config.yaml
