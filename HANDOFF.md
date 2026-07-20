# 接班提示词 — 2026-07-20

> 上一会话：12d56cfd，已完成 v2.0 管线改造。**核心未解决问题：Stella 不响应 Skill。**

---

## 项目现状

Video_to_Text v2.0 管线已完工，代码在 `e:\Desktop\Video_to_Text\`。

### 已完成的改动（全部已 git commit）

| 能力 | 说明 |
|------|------|
| 内容分析 | `content_analyzer.py` — 从文件名提取 B站 AV 号 → 调 API → 自动分类视频类型 → 生成专用 scene prompt |
| DashScope ASR | `transcriber.py` — 上传音频 → DashScope Paraformer 转录，比 faster-whisper 快 3 倍 + 自带标点 |
| 动态 prompt | `scene_describer.py` — 四种模板（meme_guide/stock_tutorial/tech_knowledge/general），按视频类型自动匹配 |
| 输出修复 | OCR 跨帧去重、自适应转录窗口、垃圾段过滤 |
| 本地 HTTP 服务 | `pipeline_server.py` — 监听 `100.80.205.79:8940`，Stella 调来触发处理 |
| Stella 集成 | `stella_bridge.py` + `--stella` flag + Skill 文件 |

### 当前服务状态

```bash
# 管线服务正在本机运行
curl http://100.80.205.79:8940/health  # → {"status": "ok"}

# 可用端点
GET  /health          # 健康检查
GET  /videos          # 列出所有视频
GET  /status          # 查看任务状态
POST /process         # 处理单个视频 {"video": "路径", "interval": 20, "asr_engine": "dashscope"}
POST /process-batch   # 批量处理目录 {"directory": "2026-07-20", "interval": 20}
```

### 视频位置

```
videos/2026-07-20/吸引力和框架合集/
  ├── 班主任高位框架课 19节/  (19 个 mp4)
  └── 社交吸引力训练营-人性课/ (12+ 个 mp4)
```

## 🔴 核心问题：Stella 不触发 Skill

### 环境
- **Stella** = OpenClaw 实例，跑在 mote-home（Ubuntu），DeepSeek V4 Flash
- **接入渠道**：企业微信机器人（API 长连接）
- **网关端口**：mote-home:18789（loopback only）
- **Skill 位置**：`~/.openclaw/workspace/skills/analyze-video/SKILL.md`（已部署，格式正确）
- **已重启 openclaw-gateway 多次**

### 现象
用户在企微发"处理 2026-07-20 下所有视频"，Stella 不调用 Skill 里定义的 curl 命令，而是去搜本地文件或调 wecom_mcp。

### 已尝试
- Skill 文件名 + frontmatter 格式对齐其他 Skill（`name`、`description`、YAML 分隔符）
- 简化 Skill 内容到单行命令
- 在 mote-home 上放了包装脚本 `~/.openclaw/workspace/process-video.sh`（已验证可正常调通 pipeline）
- 加了 Trigger Conditions 章节
- 重启 Stella 多次

### 可能方向
1. **Stella 用 DeepSeek V4 Flash**，这个模型可能不擅长执行 Skill 里定义的自主操作。OpenClaw 官方推荐 Claude 模型。
2. **需要斜杠命令触发**：OpenClaw 支持 `/skill-name` 格式。试试在企微发 `/analyze-video 处理 2026-07-20`
3. **`tools.profile: "coding"`** — Stella 配置了 coding profile，应该有 bash/exec 能力，但需要确认
4. **Workspace skills 的 auto-load 条件**：可能 description 里的关键词匹配算法需要更精确
5. **直接让 Stella 跑脚本**：`bash ~/.openclaw/workspace/process-video.sh process-dir "2026-07-20"` — 测试 Stella 到底有没有 exec 能力

### Stella 调试命令
```bash
ssh mote "systemctl status openclaw-gateway"
ssh mote "journalctl -u openclaw-gateway --since '5 min ago' --no-pager | tail -50"
ssh mote "ls ~/.openclaw/workspace/skills/"
ssh mote "cat ~/.openclaw/openclaw.json | python3 -m json.tool | head -30"
```

## 对新会话的建议

1. 先别急着改代码，**在企微上试 `/analyze-video` 斜杠命令**
2. 如果不生效，登 mote-home 查 Stella 日志看 Skill 加载情况
3. 如果 Stella 确实没有 exec 能力（DeepSeek Flash 的限制），考虑换模型或者换方案——比如用 Claude Bridge（port 8933）绕过 Stella 直达用户企微
4. 最坏情况：不用 Stella，用户在本机直接跑 `python main.py video.mp4 --interval 15`，管线本身已经全自动了
