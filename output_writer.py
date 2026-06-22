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
        "version": "1.0",
        "created": datetime.now(timezone.utc).isoformat(),
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
    """Write a human-readable Markdown report."""
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
    lines.append("")

    # -- Errors --
    if result.errors:
        lines.append("## ⚠️ Errors")
        lines.append("")
        for err in result.errors:
            lines.append(f"- {err}")
        lines.append("")

    # -- Transcript --
    lines.append("---")
    lines.append("")
    lines.append("## 📝 Transcript")
    lines.append("")
    if result.transcript:
        lines.append("| Start | End | Text |")
        lines.append("|-------|-----|------|")
        for t in result.transcript:
            lines.append(f"| {_format_time(t.start_sec)} | {_format_time(t.end_sec)} | {t.text} |")
    else:
        lines.append("*No transcript (audio may be missing).*")
    lines.append("")

    # -- Scene Analysis --
    lines.append("---")
    lines.append("")
    lines.append("## 🎬 Scene Analysis")
    lines.append("")

    if result.scene_descriptions:
        for sd in result.scene_descriptions:
            ts = _format_time(sd.timestamp_sec)
            lines.append(f"### {ts} — Frame {sd.frame_index}")
            lines.append("")

            # Summary
            if sd.summary:
                lines.append(f"**Summary**: {sd.summary}")
                lines.append("")

            # Setting
            if sd.setting:
                lines.append(f"**Setting**: {sd.setting}")
                lines.append("")

            # Objects
            if sd.objects:
                lines.append(f"**Objects**: {', '.join(sd.objects)}")
                lines.append("")

            # Actions
            if sd.actions:
                lines.append(f"**Actions**: {', '.join(sd.actions)}")
                lines.append("")

            # OCR text at this frame
            frame_ocr = [r for r in result.ocr_results if r.frame_index == sd.frame_index]
            if frame_ocr:
                lines.append("**OCR Text**:")
                for ocr_item in frame_ocr:
                    lines.append(f"- \"{ocr_item.text}\" (conf: {ocr_item.confidence})")
                lines.append("")

            # Vision-reported on-screen text
            if sd.on_screen_text:
                lines.append(f"**On-screen text (vision)**: {sd.on_screen_text}")
                lines.append("")

            lines.append("---")
            lines.append("")
    else:
        # No scene descriptions — still show OCR results with timestamps
        lines.append("*No scene descriptions (vision API may have been skipped).*")
        lines.append("")
        if result.ocr_results:
            lines.append("## 🔤 OCR Text")
            lines.append("")
            lines.append("| Timestamp | Frame | Text | Confidence |")
            lines.append("|-----------|-------|------|------------|")
            for r in result.ocr_results:
                lines.append(
                    f"| {_format_time(r.timestamp_sec)} | {r.frame_index} | "
                    f"{r.text} | {r.confidence} |"
                )
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
