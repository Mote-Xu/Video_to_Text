"""Extract keyframes from video using ffmpeg — interval, scene-detection, or smart text-aware mode."""

import re
import subprocess
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from models import KeyFrame, VideoMeta

# Cache EasyOCR reader for smart mode
_smart_ocr = None


class KeyFrameError(Exception):
    """Raised when keyframe extraction fails."""


def extract_keyframes(
    video_path: str | Path,
    video_meta: VideoMeta | None = None,
    mode: str = "scene",
    interval_sec: float = 5.0,
    scene_threshold: float = 0.3,
    output_dir: str | Path | None = None,
    image_format: str = "jpg",
    quality: int = 90,
    max_keyframes: int = 500,
) -> list[KeyFrame]:
    """
    Extract keyframes from a video.

    Parameters
    ----------
    video_path : Path to the input video.
    video_meta : Optional pre-computed VideoMeta.
    mode : "interval" (fixed N seconds) or "scene" (only when visual content changes).
    interval_sec : For "interval" mode: seconds between frames.
    scene_threshold : For "scene" mode: sensitivity 0.1-1.0 (lower = more frames).
    output_dir : Where to put extracted frames.
    image_format : "jpg" or "png".
    quality : JPEG quality 1-100.
    max_keyframes : Maximum number of keyframes.

    Returns
    -------
    List of KeyFrame objects.
    """
    video_path = Path(video_path)

    if shutil.which("ffmpeg") is None:
        raise KeyFrameError("ffmpeg not found. Install: conda install -c conda-forge ffmpeg")

    if output_dir is None:
        output_dir = Path("outputs") / "keyframes"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    if mode == "smart":
        return _extract_smart_frames(
            video_path, output_dir, image_format, quality, max_keyframes,
        )
    elif mode == "scene":
        return _extract_scene_frames(
            video_path, video_meta, output_dir, image_format,
            quality, scene_threshold, max_keyframes,
        )
    else:
        return _extract_interval_frames(
            video_path, output_dir, image_format,
            quality, interval_sec, max_keyframes,
        )


def _extract_interval_frames(
    video_path: Path,
    output_dir: Path,
    image_format: str,
    quality: int,
    interval_sec: float,
    max_keyframes: int,
) -> list[KeyFrame]:
    """Extract frames at fixed time intervals."""
    fps_filter = f"fps=1/{interval_sec}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", fps_filter,
        "-q:v", str(quality_to_qscale(quality)),
        "-frames:v", str(max_keyframes),
        "-loglevel", "error",
        str(output_dir / f"{video_path.stem}_frame_%06d.{image_format}"),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise KeyFrameError(f"ffmpeg failed:\n{result.stderr}")

    pattern = f"{video_path.stem}_frame_*.{image_format}"
    frame_paths = sorted(output_dir.glob(pattern))

    keyframes: list[KeyFrame] = []
    for idx, fp in enumerate(frame_paths, start=1):
        keyframes.append(KeyFrame(
            index=idx,
            timestamp_sec=round((idx - 1) * interval_sec, 3),
            image_path=fp,
        ))
    return keyframes


def _extract_scene_frames(
    video_path: Path,
    video_meta: VideoMeta | None,
    output_dir: Path,
    image_format: str,
    quality: int,
    threshold: float,
    max_keyframes: int,
) -> list[KeyFrame]:
    """Detect scene changes and extract one frame per scene."""

    # Pass 1: get scene change timestamps via showinfo
    threshold_str = str(threshold).replace(",", ".")
    cmd_detect = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"select='gt(scene\\,{threshold_str})',showinfo",
        "-vsync", "vfr",
        "-f", "null",
        "-loglevel", "info",
        "-",
    ]

    result = subprocess.run(cmd_detect, capture_output=True, text=True, timeout=600)
    # ffmpeg writes showinfo to stderr; non-zero exit is ok for null output

    # Parse pts_time values from showinfo lines
    timestamps: list[float] = [0.0]  # always include frame 0
    pts_pattern = re.compile(r"pts_time:([\d.]+)")
    for line in result.stderr.splitlines():
        m = pts_pattern.search(line)
        if m:
            ts = float(m.group(1))
            # Avoid duplicates (same scene)
            if not timestamps or ts - timestamps[-1] > 1.0:
                timestamps.append(ts)

    # Limit
    if len(timestamps) > max_keyframes:
        timestamps = timestamps[:max_keyframes]

    print(f"  Scene detection: {len(timestamps)} scene changes found")

    # Pass 2: extract a frame at each timestamp
    keyframes: list[KeyFrame] = []
    for idx, ts in enumerate(timestamps):
        out_name = f"{video_path.stem}_frame_{idx + 1:06d}.{image_format}"
        out_path = output_dir / out_name

        # Seek to timestamp and grab one frame
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(ts),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", str(quality_to_qscale(quality)),
            "-loglevel", "error",
            str(out_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)

        if out_path.exists():
            keyframes.append(KeyFrame(
                index=idx + 1,
                timestamp_sec=round(ts, 3),
                image_path=out_path,
            ))

    return keyframes


def _extract_smart_frames(
    video_path: Path,
    output_dir: Path,
    image_format: str,
    quality: int,
    max_keyframes: int,
) -> list[KeyFrame]:
    """Extract frames at dense intervals, keep only those with text content changes."""
    global _smart_ocr

    # Phase 1: extract frames every 2 seconds
    temp_dir = output_dir / "_smart_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", "fps=1/2",
        "-q:v", str(quality_to_qscale(quality)),
        "-frames:v", str(max_keyframes),
        "-loglevel", "error",
        str(temp_dir / f"temp_%06d.{image_format}"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise KeyFrameError(f"ffmpeg failed:\n{result.stderr}")

    frame_paths = sorted(temp_dir.glob(f"temp_*.{image_format}"))
    if not frame_paths:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return []

    # Phase 2: load EasyOCR once
    if _smart_ocr is None:
        import easyocr
        _smart_ocr = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)

    # Phase 3: OCR each frame, keep only frames with significant text change
    kept: list[KeyFrame] = []
    last_texts: set[str] = set()

    for idx, fp in enumerate(frame_paths):
        ts = idx * 2  # 2-second interval

        try:
            # Use PIL to avoid OpenCV Unicode path issues on Windows
            img = Image.open(fp).convert("RGB")
            img_np = np.array(img)
            detections = _smart_ocr.readtext(img_np)
        except Exception:
            continue

        current_texts: set[str] = set()
        for _, text, conf in detections:
            if conf >= 0.4 and text.strip():
                current_texts.add(text.strip())

        # Skip frames with no text
        if not current_texts:
            continue

        # Compare with last kept frame
        if last_texts:
            intersection = current_texts & last_texts
            union = current_texts | last_texts
            similarity = len(intersection) / len(union) if union else 0

            # Keep only if text changed significantly (< 40% overlap)
            if similarity >= 0.4:
                continue

        # Move from temp to final location
        final_name = f"{video_path.stem}_frame_{len(kept) + 1:06d}.{image_format}"
        final_path = output_dir / final_name
        fp.rename(final_path)

        kept.append(KeyFrame(
            index=len(kept) + 1,
            timestamp_sec=round(ts, 3),
            image_path=final_path,
        ))
        last_texts = current_texts

        if len(kept) >= max_keyframes:
            break

    # Cleanup temp
    shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"  Smart detection: {len(frame_paths)} raw → {len(kept)} unique text frames")
    return kept


def quality_to_qscale(quality: int) -> int:
    """Convert 1-100 quality to ffmpeg q:v scale (2-31, lower = better)."""
    clamped = max(1, min(100, quality))
    return max(2, min(31, round(31 - (clamped / 100) * 29)))
