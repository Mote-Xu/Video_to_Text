---
name: video-to-text
description: 处理视频、分析视频、视频转文字、转录视频、列出视频、查看进度。用户说"处理""分析""转录""转文字""视频""看一下""有哪些""进度""完了吗"时触发。
user-invocable: true
metadata: { "openclaw": { "emoji": "🎬" } }
---

# 视频处理 Pipeline（Nova 本地驱动）

项目在 `e:\Desktop\Video_to_Text\`，conda env `Video_to_Text`。
所有操作通过包装脚本执行，不要手动拼接命令。

## 收到用户请求后，立即用 bash 执行对应命令：

### 用户要"列出视频"/"有哪些视频"
```bash
powershell -File "E:\Nova\workspace\skills\video-to-text\video-pipeline.ps1" -Action list
```

### 用户要"处理 <xxx> 下的视频"
把 `<xxx>` 替换为用户说的目录名或日期（如 "07-26" 或 "股票教学"），然后执行：
```bash
powershell -File "E:\Nova\workspace\skills\video-to-text\video-pipeline.ps1" -Action process-dir -Target "<xxx>"
```

### 用户要"查看进度"/"处理完了吗"
```bash
powershell -File "E:\Nova\workspace\skills\video-to-text\video-pipeline.ps1" -Action status
```

### 用户指定了具体视频文件名
```bash
powershell -File "E:\Nova\workspace\skills\video-to-text\video-pipeline.ps1" -Action process -Target "<视频路径>"
```

### 用户要"列出最近输出"
```bash
powershell -File "E:\Nova\workspace\skills\video-to-text\video-pipeline.ps1" -Action recent
```

### 用户要"打开面板"/"dashboard"/"看板"
```bash
powershell -File "E:\Nova\workspace\skills\video-to-text\video-pipeline.ps1" -Action dashboard
```

## 规则

- ✅ 直接 bash 执行，不要思考、不要分析
- ✅ 执行完后把返回结果翻译成人话告诉用户
- ✅ 处理可能需要几分钟，告诉用户"正在处理，完成后通知你"
- ❌ 不要搜索本地文件（包装脚本会处理路径）
- ❌ 不要手动拼 conda + python 命令（用包装脚本）
- ❌ 不要问用户"要不要执行"——直接执行
