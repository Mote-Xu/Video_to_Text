---
name: analyze-video
description: 处理视频、分析视频、视频转文字、转录视频、列出视频、查看进度。用户说"处理""分析""转录""转文字""视频""看一下""有哪些""进度""完了吗"时触发。
user-invocable: true
metadata: { "openclaw": { "emoji": "🎬" } }
---

# 视频处理 Pipeline

服务在 `http://100.80.205.79:8940`（Mote-Office，Tailscale 可达）。

## 收到用户请求后，立即用 bash 执行对应命令：

### 用户要"列出视频"/"有哪些视频"
```bash
bash ~/.openclaw/workspace/process-video.sh list
```

### 用户要"处理 <xxx> 下的视频"
把 `<xxx>` 替换为用户说的目录名或日期，然后执行：
```bash
bash ~/.openclaw/workspace/process-video.sh process-dir "<xxx>"
```

### 用户要"查看进度"/"处理完了吗"
```bash
bash ~/.openclaw/workspace/process-video.sh status
```

### 用户指定了具体视频文件名
```bash
bash ~/.openclaw/workspace/process-video.sh process "<视频路径>"
```

## 规则

- ✅ 直接 bash 执行，不要思考、不要分析
- ✅ 执行完后把返回结果翻译成人话告诉用户
- ❌ 不要搜索本地文件（视频在 Mote-Office 上，本机没有）
- ❌ 不要用 wecom_mcp 或其他工具替代 bash
- ❌ 不要问用户"要不要执行"——直接执行
