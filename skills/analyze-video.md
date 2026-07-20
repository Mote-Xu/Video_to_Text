# analyze-video — Stella Skill 参考

Stella 的 OpenClaw Skill，通过企微触发本机 Video_to_Text 管线。

## 部署位置

`mote-home:~/.openclaw/workspace/skills/analyze-video/SKILL.md`

## 触发方式

1. **关键词自动匹配**：用户说"处理视频""列出视频""查看进度"等 → description 匹配 → 加载 Skill → 执行 bash
2. **斜杠命令**：`/analyze-video` 强制触发

## 架构

```
企微 → Stella (mote-home, OpenClaw) → bash curl → pipeline_server.py (:8940, Mote-Office) → main.py → outputs/
```

## Pipeline Server 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/videos` | 列出所有视频 |
| GET | `/status` | 任务状态 |
| POST | `/process` | 处理单个 `{"video":"路径","interval":20}` |
| POST | `/process-batch` | 批量处理 `{"directory":"2026-07-20","interval":20}` |

## 包装脚本

`mote-home:~/.openclaw/workspace/process-video.sh`
```
list        → GET /videos
process-dir → POST /process-batch
process     → POST /process
status      → GET /status
```

## 本地 Skill 副本

- `skills/SKILL.md` — 实际部署到 mote-home 的内容
- `skills/analyze-video.md` — 本文件，参考文档
