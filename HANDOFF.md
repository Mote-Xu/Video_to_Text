# 接班提示词 — 2026-08-06（已归档）

> ⚠️ 此文档已过时。项目当前状态见 [CLAUDE.md](CLAUDE.md)。

## 重大变更（2026-08-06）

项目已从 Mote-Office 笔记本迁移到 **mote-home 服务器**：
- 代码：`/mnt/data/Video_to_Text/`（`~/Video_to_Text/` symlink）
- conda 环境：`Video_to_Text`（Python 3.12）
- 处理在服务器跑，视频和输出在本机 `E:\Desktop\Video_to_Text\`

## 当前架构

```
TG → Nova (mote-home, OpenClaw :18790) → 服务器跑 pipeline → SCP 回本机
```

- pipeline_server.py 已删除
- stella_bridge.py 已删除
- Stella 已下线，Nova 取代所有功能
- Nova skill 已更新为跨机流程（本机存、服务器算、SCP 搬运）

---

以下是 2026-07-20 原始内容（仅供考古）：
