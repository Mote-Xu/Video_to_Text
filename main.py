#!/usr/bin/env python3
"""
Video-to-Text Pipeline
======================
Convert a video file into structured text output:
  1. Audio extraction + ASR transcription (faster-whisper)
  2. Keyframe extraction + scene description (Claude Vision API)
  3. OCR text extraction (PaddleOCR)

Usage:
    python main.py video.mp4
    python main.py video.mp4 --interval 10 --model medium --language zh
    python main.py video.mp4 --skip-ocr --skip-vision
    python main.py video.mp4 -o ./my_results
"""

from __future__ import annotations

import argparse
import sys
import time
import shutil
from pathlib import Path

from config import load_config, PipelineConfig
from models import PipelineResult, PipelineStats

# Ensure the project root is on sys.path so imports work
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Video-to-Text: extract transcript, scene descriptions, and OCR from video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py lecture.mp4
  python main.py video.mp4 --interval 10 --language zh
  python main.py video.mp4 --skip-vision --skip-ocr
  python main.py video.mp4 --config my_config.yaml
        """,
    )

    p.add_argument("video", type=str, help="Path to input video file.")

    p.add_argument("--config", "-c", type=str, default=None,
                   help="Path to YAML config file (default: ./config.yaml).")
    p.add_argument("--output-dir", "-o", type=str, default=None,
                   help="Output directory (overrides config).")

    # ASR
    p.add_argument("--model", type=str, choices=["tiny", "base", "small", "medium"],
                   default=None, help="Whisper model size (default: small).")
    p.add_argument("--language", type=str, default=None,
                   help="Language code override, e.g. zh, en, ja (default: auto).")
    p.add_argument("--device", type=str, choices=["cuda", "cpu"], default=None,
                   help="Device for Whisper (default: cuda).")

    # Keyframes
    p.add_argument("--interval", type=float, default=None,
                   help="Seconds between keyframes (default: 5.0).")

    # OCR
    p.add_argument("--ocr-gpu", action="store_true", default=None,
                   help="Run OCR on GPU (may conflict with Whisper VRAM).")
    p.add_argument("--ocr-lang", type=str, default=None,
                   help="PaddleOCR language (default: ch).")

    # Vision
    p.add_argument("--vision-model", type=str, default=None,
                   help="Claude model for vision (default: claude-sonnet-4-20250514).")

    # Toggles
    p.add_argument("--skip-asr", action="store_true", help="Skip ASR transcription.")
    p.add_argument("--skip-ocr", action="store_true", help="Skip OCR extraction.")
    p.add_argument("--skip-vision", action="store_true", help="Skip scene description.")
    p.add_argument("--skip-keyframes", action="store_true",
                   help="Skip keyframe extraction (implies --skip-ocr and --skip-vision).")

    # Output options
    p.add_argument("--no-json", action="store_true", help="Suppress JSON output.")
    p.add_argument("--no-markdown", action="store_true", help="Suppress Markdown output.")
    p.add_argument("--srt", action="store_true", help="Also generate SRT subtitle file.")
    p.add_argument("--keep-temp", action="store_true", help="Keep temporary files.")

    return p


def _build_overrides(args: argparse.Namespace) -> dict:
    """Convert parsed CLI args into dot-notation config overrides."""
    overrides: dict = {}

    if args.model is not None:
        overrides["asr.model_size"] = args.model
    if args.language is not None:
        overrides["asr.language"] = args.language
    if args.device is not None:
        overrides["asr.device"] = args.device
    if args.interval is not None:
        overrides["keyframe.interval_sec"] = args.interval
    if args.ocr_gpu is not None:
        overrides["ocr.use_gpu"] = True
    if args.ocr_lang is not None:
        overrides["ocr.lang"] = args.ocr_lang
    if args.vision_model is not None:
        overrides["vision.model"] = args.vision_model
    if args.output_dir is not None:
        overrides["output.dir"] = args.output_dir

    return overrides


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    video_path: str,
    config: PipelineConfig,
    *,
    skip_asr: bool = False,
    skip_ocr: bool = False,
    skip_vision: bool = False,
    no_json: bool = False,
    no_markdown: bool = False,
    write_srt: bool = False,
    keep_temp: bool = False,
) -> PipelineResult:
    """Execute the full video-to-text pipeline."""
    # If skip_keyframes, also skip OCR and vision
    result = PipelineResult(video=None)  # type: ignore[arg-type]
    stats = PipelineStats()
    t_total_start = time.perf_counter()

    # -- Phase 0: Probe video --
    print("=" * 60)
    print("Video-to-Text Pipeline")
    print("=" * 60)

    from audio_extractor import probe_video
    print(f"\n[1/5] Probing: {video_path}")
    video_meta = probe_video(video_path)
    result.video = video_meta
    print(f"  Resolution: {video_meta.width}x{video_meta.height} | "
          f"Duration: {video_meta.duration_sec:.1f}s | FPS: {video_meta.fps:.1f}")
    print(f"  Has audio: {video_meta.has_audio}")
    video_stem = video_meta.path.stem

    # -- Phase 1: Extract audio --
    if not skip_asr and video_meta.has_audio:
        print(f"\n[2/5] Extracting audio...")
        t0 = time.perf_counter()
        from audio_extractor import extract_audio
        audio_path = extract_audio(
            video_path,
            sample_rate=config.video.sample_rate,
            channels=config.video.channels,
        )
        stats.audio_extraction_sec = round(time.perf_counter() - t0, 2)
        print(f"  Audio: {audio_path} ({stats.audio_extraction_sec}s)")
    elif skip_asr:
        print(f"\n[2/5] Audio extraction: SKIPPED")
    else:
        print(f"\n[2/5] Audio extraction: NO AUDIO TRACK")
        skip_asr = True  # can't transcribe without audio

    # -- Phase 2: Extract keyframes --
    if not skip_ocr or not skip_vision:
        print(f"\n[3/5] Extracting keyframes (every {config.keyframe.interval_sec}s)...")
        t0 = time.perf_counter()
        from keyframe_extractor import extract_keyframes
        keyframe_dir = Path(config.output.dir) / video_stem / "keyframes"
        keyframes = extract_keyframes(
            video_path,
            video_meta=video_meta,
            interval_sec=config.keyframe.interval_sec,
            output_dir=keyframe_dir,
            image_format=config.keyframe.format,
            quality=config.keyframe.quality,
            max_keyframes=config.keyframe.max_keyframes,
        )
        stats.keyframe_extraction_sec = round(time.perf_counter() - t0, 2)
        result.keyframes = keyframes
        print(f"  Extracted {len(keyframes)} keyframes ({stats.keyframe_extraction_sec}s)")
    else:
        print(f"\n[3/5] Keyframe extraction: SKIPPED")

    # -- Phase 3: ASR transcription --
    if not skip_asr and video_meta.has_audio:
        print(f"\n[4/5] Transcribing (model: {config.asr.model_size}, device: {config.asr.device})...")
        t0 = time.perf_counter()
        from transcriber import transcribe
        transcript = transcribe(
            audio_path,
            model_size=config.asr.model_size,
            device=config.asr.device,
            compute_type=config.asr.compute_type,
            language=config.asr.language,
            beam_size=config.asr.beam_size,
            vad_filter=config.asr.vad_filter,
            word_timestamps=config.asr.word_timestamps,
        )
        stats.asr_transcription_sec = round(time.perf_counter() - t0, 2)
        result.transcript = transcript
        print(f"  Transcript: {len(transcript)} segments ({stats.asr_transcription_sec}s)")
    else:
        print(f"\n[4/5] ASR transcription: SKIPPED")

    # -- Phase 4: OCR --
    if not skip_ocr and result.keyframes:
        print(f"\n[4.5/5] Running OCR (engine: {config.ocr.engine}, lang: {config.ocr.lang})...")
        t0 = time.perf_counter()
        from ocr_extractor import run_ocr
        ocr_results = run_ocr(
            result.keyframes,
            lang=config.ocr.lang,
            use_gpu=config.ocr.use_gpu,
            conf_threshold=config.ocr.conf_threshold,
        )
        stats.ocr_sec = round(time.perf_counter() - t0, 2)
        result.ocr_results = ocr_results
        print(f"  OCR: {len(ocr_results)} text detections ({stats.ocr_sec}s)")
    elif skip_ocr:
        print(f"\n[4.5/5] OCR: SKIPPED")

    # -- Phase 5: Scene description --
    if not skip_vision and result.keyframes:
        # Choose the right API key based on provider
        provider = config.vision.provider
        if provider == "gemini":
            api_key = config.gemini_api_key
        elif provider == "deepseek":
            api_key = config.deepseek_api_key
        elif provider == "anthropic":
            api_key = config.anthropic_api_key
        else:
            api_key = config.gemini_api_key  # fallback

        print(f"\n[5/5] Describing scenes (provider: {provider}, model: {config.vision.model})...")
        t0 = time.perf_counter()
        from scene_describer import describe_scenes
        try:
            descriptions = describe_scenes(
                result.keyframes,
                api_key=api_key,
                provider=provider,
                model=config.vision.model,
                max_tokens=config.vision.max_tokens,
                temperature=config.vision.temperature,
            )
            stats.vision_sec = round(time.perf_counter() - t0, 2)
            result.scene_descriptions = descriptions
            print(f"  Scenes: {len(descriptions)} described ({stats.vision_sec}s)")
        except Exception as e:
            result.errors.append(f"Vision: {e}")
            print(f"  Vision FAILED: {e}")
    else:
        print(f"\n[5/5] Scene description: SKIPPED")

    # -- Phase 6: Output --
    stats.total_sec = round(time.perf_counter() - t_total_start, 2)
    result.stats = stats

    print(f"\n{'=' * 60}")
    print(f"Pipeline complete in {stats.total_sec:.1f}s")
    print(f"{'=' * 60}")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = build_parser().parse_args()

    # Load config
    cli_overrides = _build_overrides(args)
    config = load_config(args.config, cli_overrides)

    # Determine skip flags
    skip_asr = args.skip_asr
    skip_ocr = args.skip_ocr or args.skip_keyframes
    skip_vision = args.skip_vision or args.skip_keyframes

    # Run pipeline
    result = run_pipeline(
        args.video,
        config,
        skip_asr=skip_asr,
        skip_ocr=skip_ocr,
        skip_vision=skip_vision,
        no_json=args.no_json,
        no_markdown=args.no_markdown,
        write_srt=args.srt,
        keep_temp=args.keep_temp,
    )

    # Write outputs — one subfolder per video
    output_video_stem = result.video.path.stem
    output_dir = Path(config.output.dir) / output_video_stem
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    if not args.no_json:
        json_path = output_dir / "report.json"
        from output_writer import write_json
        write_json(result, json_path)
        print(f"  JSON: {json_path}")

    # Markdown
    if not args.no_markdown:
        md_path = output_dir / "report.md"
        from output_writer import write_markdown
        write_markdown(result, md_path)
        print(f"  Markdown: {md_path}")

    # SRT
    if args.srt and result.transcript:
        srt_path = output_dir / "transcript.srt"
        from output_writer import write_srt
        write_srt(result, srt_path, config.output.srt_max_chars_per_line)
        print(f"  SRT: {srt_path}")

    # Cleanup temp
    if not args.keep_temp:
        temp_dir = Path("temp")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            print(f"  Temp files cleaned up.")

    print("\nDone.")

    # Return non-zero exit if any errors
    if result.errors:
        print(f"\n⚠ {len(result.errors)} error(s) occurred:")
        for e in result.errors:
            print(f"  - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
