"""Content analyzer — detect video type and generate dynamic scene description prompts.

Two strategies:
1. B站 API: extract AV/BV number from filename → fetch title/tags/partition → classify
2. Local fallback: sample first N ASR segments → ask DeepSeek to classify
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ContentProfile:
    """Result of content analysis — used to generate scene description prompt."""

    video_type: str = ""          # "meme_guide" | "stock_tutorial" | "tech_edu" | "general"
    video_type_label: str = ""    # Human-readable label: "梗指南/网络文化" | "股票技术分析"
    topics: list[str] = field(default_factory=list)   # ["内卷", "打工人"]
    source: str = ""              # "bilibili" | "local_fallback" | "unknown"
    bilibili_url: str = ""        # Original B站 URL if found
    title: str = ""
    tags: list[str] = field(default_factory=list)
    partition: str = ""           # B站分区名
    suggested_prompt: str = ""    # The generated scene description prompt


# ---------------------------------------------------------------------------
# B站 AV/BV number extraction
# ---------------------------------------------------------------------------

AV_PATTERN = re.compile(r"[Aa][Vv](\d+)", re.IGNORECASE)
BV_PATTERN = re.compile(r"[Bb][Vv]([A-Za-z0-9]{10})", re.IGNORECASE)


def extract_bilibili_id(filename: str) -> tuple[str | None, str | None]:
    """Extract (avid, bvid) from a filename. Returns (None, None) if not found."""
    av_match = AV_PATTERN.search(filename)
    if av_match:
        return (av_match.group(1), None)

    bv_match = BV_PATTERN.search(filename)
    if bv_match:
        return (None, bv_match.group(0))

    return (None, None)


# ---------------------------------------------------------------------------
# B站 API
# ---------------------------------------------------------------------------

BILIBILI_VIEW_API = "https://api.bilibili.com/x/web-interface/view/detail"
BILIBILI_CARD_API = "https://api.bilibili.com/x/web-interface/card"


def fetch_bilibili_info(
    avid: str | None = None,
    bvid: str | None = None,
    timeout: int = 10,
) -> dict | None:
    """Fetch video info from B站 API. Returns parsed JSON dict or None."""
    if bvid:
        url = f"{BILIBILI_VIEW_API}?bvid={bvid}"
    elif avid:
        url = f"{BILIBILI_VIEW_API}?aid={avid}"
    else:
        return None

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"  ⚠ B站 API 请求失败: {e}")
        return None

    if data.get("code") != 0:
        print(f"  ⚠ B站 API 返回错误: {data.get('message', 'unknown')}")
        return None

    inner = data.get("data", {})

    # /view/detail wraps video info in "View" key
    video_data = inner.get("View", inner)

    # Tags are at the data level (sibling of View)
    if "Tags" in inner:
        video_data["Tags"] = inner["Tags"]

    # Also grab Card for description/stat
    if "Card" in inner:
        video_data["Card"] = inner["Card"]

    return video_data


# ---------------------------------------------------------------------------
# Video type classification & prompt generation
# ---------------------------------------------------------------------------

# Mapping from B站 partition IDs to video types
# https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/video/video_zone.md
PARTITION_MAP: dict[int, str] = {
    # 知识
    36: "knowledge",
    201: "tech_science",
    207: "finance_business",
    208: "career",  # 职场
    209: "design",
    # 生活
    160: "lifestyle",
    138: "comedy",
    # 娱乐
    4: "entertainment",
    119: "anime_commentary",  # 动漫杂谈
    155: "meme",  # 梗/搞笑
    # 科技
    188: "tech",
    95: "digital",
    230: "programming",
    # 游戏
    1: "game",
    140: "game_commentary",
    # 资讯
    202: "news",
    203: "social",
}

# Rich prompt templates per video type
PROMPT_TEMPLATES: dict[str, str] = {
    "meme_guide": """You are analyzing frames from a Chinese internet meme / pop culture explainer video ("梗指南" / "梗百科"). Describe what you see in a way that helps understand the meme being explained.

Return ONLY valid JSON (no markdown):
{
  "summary": "Describe exactly what is shown: the meme image/screenshot, any text overlays, the visual style. What is the key element being explained?",
  "objects": ["visible elements: characters, text, screenshots, props"],
  "actions": ["what is happening: narrator pointing, text animation, meme reaction"],
  "setting": "video format: talking head / screen recording / animation / slide deck",
  "on_screen_text": "ALL visible text — meme captions, B站 UI, subtitles, watermarks"
}""",

    "stock_tutorial": """You are analyzing frames from a Chinese stock trading tutorial video. Describe ONLY what you can actually see — do NOT invent indicators or patterns that are not clearly visible.

Return ONLY valid JSON (no markdown):
{
  "summary": "Describe what the chart shows: uptrend/downtrend/consolidation, how many MA lines visible, any obvious patterns. Be honest if the chart is unclear.",
  "objects": ["chart elements: candlesticks, MA lines (count how many), volume bars, any indicators shown"],
  "actions": ["what the instructor is doing: pointing at chart, drawing lines, switching timeframes"],
  "setting": "trading platform name if visible, or 'presentation slide'",
  "on_screen_text": "ANY visible numbers: stock codes, prices, MA values, indicator readings, timeframes"
}""",

    "tech_science": """You are analyzing frames from a technology / science educational video. Describe what you see objectively.

Return ONLY valid JSON (no markdown):
{
  "summary": "Describe the visual content: diagrams, code, hardware, experiments, data visualizations shown on screen.",
  "objects": ["visible elements: circuit diagrams, code editors, hardware, lab equipment, UI screenshots"],
  "actions": ["what is happening: code being written, hardware being assembled, animation playing"],
  "setting": "screen recording / lab / workshop / slide deck",
  "on_screen_text": "key text visible: code snippets, terminal output, labels, annotations"
}""",

    "knowledge": """You are analyzing frames from a social commentary / documentary video (时评/社会分析). Describe visual content with attention to socio-economic context — data charts, news headlines, documentary footage, interview clips, historical imagery.

Return ONLY valid JSON (no markdown):
{
  "summary": "Describe the visual content: what data/charts/images are shown? What point is being made? Note any statistics, headlines, or documentary footage.",
  "objects": ["key visual elements: charts, news clips, people, locations, text overlays"],
  "actions": ["what is happening: narrator explaining data, interview clip playing, documentary footage"],
  "setting": "news/documentary style, talking head, data visualization, or on-location footage",
  "on_screen_text": "ALL visible text: headlines, statistics, data labels, subtitles, source citations"
}""",

    "general": """You are analyzing frames from a video. Describe what you see objectively and concisely.

Return ONLY valid JSON (no markdown):
{
  "summary": "Describe the scene: what is shown, the visual style, the main subject.",
  "objects": ["key visible elements"],
  "actions": ["what is happening in this frame"],
  "setting": "indoor/outdoor, screen recording, animation, or other",
  "on_screen_text": "any visible text, subtitles, labels, UI elements"
}""",
}


def classify_video(bilibili_data: dict | None, filename: str) -> tuple[str, str]:
    """
    Classify video type from B站 metadata + filename heuristics.
    Returns (video_type_key, human_label).
    """
    if bilibili_data:
        # Check tid and tid_v2
        tid = bilibili_data.get("tid", 0)
        tid_v2 = bilibili_data.get("tid_v2", 0)
        for t in [tid_v2, tid]:
            if t in PARTITION_MAP:
                mapped = PARTITION_MAP[t]
                if mapped == "finance_business":
                    return ("stock_tutorial", "股票技术分析")
                if mapped in ("meme", "comedy"):
                    return ("meme_guide", "梗/网络文化")
                if mapped == "tech_science":
                    return ("tech_science", "科技/科普")
                if mapped == "career":
                    return ("knowledge", "职场/知识")

        # Check tags (B站 uses capital "Tags")
        tags = bilibili_data.get("Tags") or bilibili_data.get("tags") or []
        tag_texts = [t.get("tag_name", "") if isinstance(t, dict) else str(t) for t in tags]
        all_tags = " ".join(tag_texts)
        title = bilibili_data.get("title", "")

        if any(kw in all_tags or kw in title for kw in ["梗", "梗指南", "梗百科"]):
            return ("meme_guide", "梗/网络文化")
        if any(kw in all_tags or kw in title for kw in ["股票", "炒股", "K线", "均线", "MACD", "技术分析"]):
            return ("stock_tutorial", "股票技术分析")
        if any(kw in all_tags or kw in title for kw in ["编程", "代码", "教程", "开发"]):
            return ("tech_science", "科技/编程")
        if any(kw in all_tags or kw in title for kw in ["键政", "社会", "时评", "政治"]):
            return ("knowledge", "时评/社会")

    # Fallback: keyword heuristics on filename
    fn_lower = filename.lower()
    if any(kw in fn_lower for kw in ["梗指南", "梗百科", "是什么梗"]):
        return ("meme_guide", "梗/网络文化")
    if any(kw in fn_lower for kw in ["均线", "macd", "kdj", "炒股", "操盘", "战法", "金叉", "死叉"]):
        return ("stock_tutorial", "股票技术分析")
    if any(kw in fn_lower for kw in ["python", "react", "vue", "编程", "代码", "rust"]):
        return ("tech_science", "科技/编程")

    return ("general", "通用")


def generate_scene_prompt(video_type: str, context: dict | None = None) -> str:
    """
    Generate a scene description prompt based on video type.
    Optionally enriched with B站 metadata and Stella context.
    """
    prompt = PROMPT_TEMPLATES.get(video_type, PROMPT_TEMPLATES["general"])

    # Optionally prepend context hints
    if context:
        hints: list[str] = []
        if context.get("title"):
            hints.append(f"Video title: {context['title']}")
        if context.get("partition"):
            hints.append(f"Category: {context['partition']}")
        if context.get("topics"):
            hints.append(f"Topics: {', '.join(context['topics'][:5])}")
        if context.get("key_terms"):
            hints.append(f"Key terms: {', '.join(context['key_terms'][:10])}")
        if context.get("style_notes"):
            hints.append(f"Video style: {context['style_notes']}")
        if context.get("comments_summary"):
            hints.append(f"Viewer comments context: {context['comments_summary']}")
        if hints:
            prefix = "Context:\n" + "\n".join(hints) + "\n\n"
            prompt = prefix + prompt

    return prompt


# ---------------------------------------------------------------------------
# Local fallback: classify from ASR sample
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """You are classifying a Chinese video based on its first few transcribed sentences.
Determine the video type and key topics.

Return ONLY valid JSON:
{
  "video_type": "meme_guide" | "stock_tutorial" | "tech_science" | "knowledge" | "general",
  "confidence": 0.0-1.0,
  "topics": ["topic1", "topic2"],
  "reasoning": "brief one-sentence reason"
}

Transcription samples:"""


def classify_from_transcript(
    transcript_segments: list,
    deepseek_api_key: str,
) -> dict | None:
    """Use DeepSeek to classify video type from a few ASR segments."""
    if not transcript_segments or not deepseek_api_key:
        return None

    from openai import OpenAI

    samples_text = "\n".join(
        f"[{s.start_sec:.0f}s] {s.text}"
        for s in transcript_segments[:10]
    )

    client = OpenAI(api_key=deepseek_api_key, base_url="https://api.deepseek.com")

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=200,
            temperature=0.1,
            messages=[{"role": "user", "content": f"{CLASSIFY_PROMPT}\n\n{samples_text}"}],
        )
        raw = response.choices[0].message.content
        # Extract JSON
        raw = raw.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        print(f"  ⚠ LLM classification failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_content(
    video_path: str | Path,
    transcript_preview: list | None = None,
    deepseek_api_key: str = "",
    bilibili_enabled: bool = True,
    bilibili_timeout: int = 10,
    local_fallback: bool = True,
) -> ContentProfile:
    """
    Analyze video content and generate a ContentProfile.

    Parameters
    ----------
    video_path : Path to video file.
    transcript_preview : Optional first N TranscriptSegments for LLM classification.
    deepseek_api_key : DeepSeek API key for LLM fallback.
    bilibili_enabled : Try B站 API.
    bilibili_timeout : API timeout in seconds.
    local_fallback : Use LLM fallback if B站 info unavailable.

    Returns
    -------
    ContentProfile with video type and suggested scene prompt.
    """
    filename = Path(video_path).name
    profile = ContentProfile()

    # Strategy 1: B站 API
    if bilibili_enabled:
        avid, bvid = extract_bilibili_id(filename)
        if avid or bvid:
            print(f"  B站: 检测到 {'AV'+avid if avid else bvid}")
            data = fetch_bilibili_info(avid=avid, bvid=bvid, timeout=bilibili_timeout)
            if data:
                profile.source = "bilibili"
                profile.title = data.get("title", "")
                profile.partition = data.get("tname_v2") or data.get("tname", "")
                # B站 API uses capital-T "Tags" (not "tags")
                tags = data.get("Tags") or data.get("tags") or []
                profile.tags = [t.get("tag_name", "") if isinstance(t, dict) else str(t) for t in tags]
                avid_val = data.get("aid", avid)
                bvid_val = data.get("bvid", bvid)
                profile.bilibili_url = f"https://www.bilibili.com/video/av{avid_val}" if avid_val else f"https://www.bilibili.com/video/{bvid_val}"

                vtype, vlabel = classify_video(data, filename)
                profile.video_type = vtype
                profile.video_type_label = vlabel
                profile.topics = _extract_topics(data, profile.tags, vtype)
                profile.suggested_prompt = generate_scene_prompt(vtype, {
                    "title": profile.title,
                    "partition": profile.partition,
                    "topics": profile.topics,
                })
                print(f"  类型: {vlabel} | 分区: {profile.partition} | 标签: {', '.join(profile.tags[:5])}")
                return profile
            else:
                print(f"  B站: API 获取失败，尝试本地分类...")

    # Strategy 2: Heuristic from filename
    vtype, vlabel = classify_video(None, filename)
    if vtype != "general":
        profile.source = "filename_heuristic"
        profile.video_type = vtype
        profile.video_type_label = vlabel
        profile.suggested_prompt = generate_scene_prompt(vtype)
        print(f"  类型: {vlabel} (从文件名推断)")
        return profile

    # Strategy 3: LLM fallback from ASR preview
    if local_fallback and transcript_preview and deepseek_api_key:
        print(f"  尝试 LLM 分类 ({len(transcript_preview)} 条转录样本)...")
        result = classify_from_transcript(transcript_preview, deepseek_api_key)
        if result:
            vtype = result.get("video_type", "general")
            vtype = vtype if vtype in PROMPT_TEMPLATES else "general"
            profile.source = "llm_fallback"
            profile.video_type = vtype
            profile.video_type_label = {
                "meme_guide": "梗/网络文化",
                "stock_tutorial": "股票技术分析",
                "tech_science": "科技/科普",
                "knowledge": "知识/时评",
            }.get(vtype, "通用")
            profile.topics = result.get("topics", [])
            profile.suggested_prompt = generate_scene_prompt(vtype, {
                "topics": profile.topics,
            })
            print(f"  类型: {profile.video_type_label} (LLM 推断)")
            return profile

    # Fallback to general
    profile.source = "fallback_general"
    profile.video_type = "general"
    profile.video_type_label = "通用"
    profile.suggested_prompt = PROMPT_TEMPLATES["general"]
    print(f"  类型: 通用 (无法确定)")
    return profile


def _extract_topics(data: dict, tags: list[str], vtype: str) -> list[str]:
    """Extract meaningful topic keywords from B站 metadata."""
    topics: list[str] = []

    title = data.get("title", "")
    desc = data.get("desc", "")

    # From title: extract text after "是什么梗" or before "【"
    title_clean = re.sub(r"【.*?】", "", title).strip()
    if title_clean:
        topics.append(title_clean[:30])

    # From tags: first 3 non-generic tags
    generic = {"bilibili", "B站", "视频", "原创", "自制"}
    for tag in tags[:8]:
        if tag.lower() not in {g.lower() for g in generic} and tag not in topics:
            topics.append(tag)
            if len(topics) >= 5:
                break

    return topics
