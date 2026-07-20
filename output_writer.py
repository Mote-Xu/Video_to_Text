"""Output formatters — JSON, Markdown, and optional SRT."""

import json
from datetime import datetime, timezone
from pathlib import Path

from models import PipelineResult


def _format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_json(result: PipelineResult, output_path: Path) -> None:
    """Write full pipeline result as a JSON report."""
    data = {
        "version": "2.0",
        "created": datetime.now(timezone.utc).isoformat(),
        "content_analysis": result.content_profile,
        "video": {
            "path": str(result.video.path),
            "filename": result.video.filename,
            "duration_sec": result.video.duration_sec,
            "fps": result.video.fps,
            "width": result.video.width,
            "height": result.video.height,
            "codec": result.video.codec,
        },
        "transcript": [
            {
                "start_sec": t.start_sec,
                "end_sec": t.end_sec,
                "text": t.text,
                "confidence": t.confidence,
                "language": t.language,
            }
            for t in result.transcript
        ],
        "ocr": [
            {
                "text": r.text,
                "confidence": r.confidence,
                "frame_index": r.frame_index,
                "timestamp_sec": r.timestamp_sec,
            }
            for r in result.ocr_results
        ],
        "scene_descriptions": [
            {
                "frame_index": s.frame_index,
                "timestamp_sec": s.timestamp_sec,
                "summary": s.summary,
                "objects": s.objects,
                "actions": s.actions,
                "setting": s.setting,
                "on_screen_text": s.on_screen_text,
            }
            for s in result.scene_descriptions
        ],
        "stats": {
            "audio_extraction_sec": result.stats.audio_extraction_sec,
            "asr_transcription_sec": result.stats.asr_transcription_sec,
            "keyframe_extraction_sec": result.stats.keyframe_extraction_sec,
            "ocr_sec": result.stats.ocr_sec,
            "vision_sec": result.stats.vision_sec,
            "total_sec": result.stats.total_sec,
            "vision_tokens_used": result.stats.vision_tokens_used,
        },
        "errors": result.errors,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_markdown(result: PipelineResult, output_path: Path) -> None:
    """Write a human-readable Markdown report — timeline format."""
    lines: list[str] = []
    v = result.video

    # -- Header --
    lines.append(f"# Video Analysis: {v.filename}")
    lines.append("")
    duration_str = _format_time(v.duration_sec)
    lines.append(
        f"**Duration**: {duration_str} | "
        f"**Resolution**: {v.width}x{v.height} | "
        f"**FPS**: {v.fps:.1f}"
    )
    lines.append(f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Content analysis section
    cp = result.content_profile
    if cp:
        lines.append("")
        lines.append("## 📋 Content Analysis")
        lines.append("")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 类型 | {cp.get('video_type_label', 'N/A')} |")
        lines.append(f"| 来源 | {cp.get('source', 'N/A')} |")
        if cp.get('title'):
            lines.append(f"| 标题 | {cp['title']} |")
        if cp.get('partition'):
            lines.append(f"| 分区 | {cp['partition']} |")
        if cp.get('tags'):
            lines.append(f"| 标签 | {', '.join(cp['tags'][:8])} |")
        if cp.get('topics'):
            lines.append(f"| 主题 | {', '.join(cp['topics'][:5])} |")
        if cp.get('bilibili_url'):
            lines.append(f"| B站链接 | {cp['bilibili_url']} |")
    lines.append("")

    # -- Errors --
    if result.errors:
        lines.append("## ⚠️ Errors")
        lines.append("")
        for err in result.errors:
            lines.append(f"- {err}")
        lines.append("")

    # -- Build timeline: one entry per scene description frame --
    # Group OCR by frame_index
    ocr_by_frame: dict[int, list[str]] = {}
    for r in result.ocr_results:
        ocr_by_frame.setdefault(r.frame_index, []).append(r.text)

    # Find overlapping transcript segments for each scene frame
    transcript = result.transcript or []
    t_idx = 0  # cursor into transcript list

    lines.append("---")
    lines.append("")
    lines.append("## 📖 Timeline")
    lines.append("")

    if result.scene_descriptions:
        # Adaptive window: short videos get tighter transcript matching
        video_dur = result.video.duration_sec
        total_frames = len(result.scene_descriptions)
        frame_interval = video_dur / total_frames if total_frames else 5

        if video_dur < 60:
            window_sec = frame_interval * 1.2  # ~1 frame worth of audio
        elif video_dur < 300:
            window_sec = max(10, frame_interval * 2)
        elif video_dur < 1800:
            window_sec = 30
        else:
            window_sec = 45

        for sd in result.scene_descriptions:
            ts = _format_time(sd.timestamp_sec)
            lines.append(f"### {ts} — Frame {sd.frame_index}")
            lines.append("")

            # Scene description
            if sd.summary:
                lines.append(f"**画面**: {sd.summary}")
                lines.append("")

            # Find transcript segments that fall within ±window of this frame
            frame_ts = sd.timestamp_sec
            relevant_transcript: list[str] = []
            while t_idx < len(transcript) and transcript[t_idx].end_sec < frame_ts - window_sec:
                t_idx += 1  # skip old segments
            temp_idx = t_idx
            while temp_idx < len(transcript) and transcript[temp_idx].start_sec < frame_ts + window_sec:
                seg = transcript[temp_idx]
                if seg.end_sec >= frame_ts - window_sec:
                    seg_start = _format_time(seg.start_sec)
                    relevant_transcript.append(f"[{seg_start}] {seg.text}")
                temp_idx += 1

            if relevant_transcript:
                lines.append("**同期讲解**:")
                lines.append("")
                combined = " ".join(relevant_transcript)
                # Wrap at ~120 chars
                while len(combined) > 120:
                    br = combined.rfind(" ", 0, 120)
                    if br < 60:
                        br = 120
                    lines.append(f"> {combined[:br].strip()}")
                    combined = combined[br:].strip()
                if combined:
                    lines.append(f"> {combined}")
                lines.append("")

            # OCR text at this frame
            frame_ocr = ocr_by_frame.get(sd.frame_index, [])
            if frame_ocr:
                lines.append("**屏幕文字**:")
                for txt in frame_ocr[:10]:
                    lines.append(f"- {txt}")
                if len(frame_ocr) > 10:
                    lines.append(f"- ...等 {len(frame_ocr)} 条")
                lines.append("")

            lines.append("---")
            lines.append("")
    else:
        lines.append("*No scene descriptions.*")
        lines.append("")

    # -- Show any remaining transcript (after last frame) --
    remaining = [t for t in transcript if t.start_sec > (result.scene_descriptions[-1].timestamp_sec + 30 if result.scene_descriptions else 0)]
    if remaining:
        lines.append("### 📝 后续讲解")
        lines.append("")
        lines.append("| Start | End | Text |")
        lines.append("|-------|-----|------|")
        for t in remaining:
            lines.append(f"| {_format_time(t.start_sec)} | {_format_time(t.end_sec)} | {t.text} |")
        lines.append("")

    # -- Stats --
    lines.append("## 📊 Processing Stats")
    lines.append("")
    s = result.stats
    lines.append("| Stage | Duration |")
    lines.append("|-------|----------|")
    lines.append(f"| Audio extraction | {s.audio_extraction_sec:.1f}s |")
    lines.append(f"| ASR transcription | {s.asr_transcription_sec:.1f}s |")
    lines.append(f"| Keyframe extraction | {s.keyframe_extraction_sec:.1f}s |")
    lines.append(f"| OCR | {s.ocr_sec:.1f}s |")
    lines.append(f"| Scene description | {s.vision_sec:.1f}s |")
    lines.append(f"| **Total** | **{s.total_sec:.1f}s** |")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_srt(result: PipelineResult, output_path: Path, max_chars: int = 42) -> None:
    """Write transcript as SRT subtitle file."""
    if not result.transcript:
        return

    entries: list[str] = []
    for i, t in enumerate(result.transcript, start=1):
        # Split long lines if needed
        text = t.text
        if len(text) > max_chars:
            # Simple line break at nearest space
            mid = max_chars
            space_idx = text.rfind(" ", 0, mid)
            if space_idx > max_chars // 2:
                mid = space_idx
            text = text[:mid].strip() + "\n" + text[mid:].strip()

        entries.append(
            f"{i}\n"
            f"{_format_srt_time(t.start_sec)} --> {_format_srt_time(t.end_sec)}\n"
            f"{text}\n"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))
