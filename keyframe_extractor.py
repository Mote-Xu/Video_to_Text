"""Extract keyframes from video at regular intervals using ffmpeg."""

import subprocess
import shutil
from pathlib import Path

from models import KeyFrame, VideoMeta


class KeyFrameError(Exception):
    """Raised when keyframe extraction fails."""


def extract_keyframes(
    video_path: str | Path,
    video_meta: VideoMeta | None = None,
    interval_sec: float = 5.0,
    output_dir: str | Path | None = None,
    image_format: str = "jpg",
    quality: int = 90,
    max_keyframes: int = 2000,
) -> list[KeyFrame]:
    """
    Extract keyframes from a video at regular intervals.

    Parameters
    ----------
    video_path : Path to the input video.
    video_meta : Optional pre-computed VideoMeta (avoids re-probing).
    interval_sec : Extract one frame every N seconds.
    output_dir : Where to put extracted frames. Defaults to ``outputs/keyframes/``.
    image_format : "jpg" or "png".
    quality : JPEG quality 1-100 (ignored for PNG).
    max_keyframes : Maximum number of keyframes to extract.

    Returns
    -------
    List of KeyFrame objects with index, timestamp, and image path.
    """
    video_path = Path(video_path)

    if shutil.which("ffmpeg") is None:
        raise KeyFrameError("ffmpeg not found. Install: conda install -c conda-forge ffmpeg")

    if output_dir is None:
        output_dir = Path("outputs") / "keyframes"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Build ffmpeg filter: select one frame every N seconds
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
        raise KeyFrameError(f"ffmpeg keyframe extraction failed:\n{result.stderr}")

    # Collect output files sorted by name
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


def quality_to_qscale(quality: int) -> int:
    """Convert 1-100 quality to ffmpeg q:v scale (2-31, lower = better)."""
    # Map: quality 100 → q:v 2, quality 1 → q:v 31
    clamped = max(1, min(100, quality))
    return max(2, min(31, round(31 - (clamped / 100) * 29)))
