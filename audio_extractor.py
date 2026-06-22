"""Extract audio from video using ffmpeg."""

import subprocess
import shutil
from pathlib import Path

from models import VideoMeta


class AudioExtractionError(Exception):
    """Raised when audio extraction fails."""


def _check_ffmpeg() -> None:
    """Ensure ffmpeg is available on PATH."""
    if shutil.which("ffmpeg") is None:
        raise AudioExtractionError(
            "ffmpeg not found. Install it with:\n"
            "  conda install -c conda-forge ffmpeg"
        )


def probe_video(video_path: str | Path) -> VideoMeta:
    """Extract video metadata using ffprobe."""
    _check_ffmpeg()
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # ffprobe to get JSON stream info
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise AudioExtractionError(f"ffprobe failed:\n{result.stderr}")

    import json
    data = json.loads(result.stdout)

    format_info = data.get("format", {})
    duration = float(format_info.get("duration", 0))
    streams = data.get("streams", [])

    # Find first video stream
    video_stream = None
    audio_stream = None
    for s in streams:
        if s.get("codec_type") == "video" and video_stream is None:
            video_stream = s
        elif s.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = s

    if video_stream is None:
        raise AudioExtractionError("No video stream found in file.")

    # Parse fps — can be a fraction like "30000/1001"
    fps_str = video_stream.get("avg_frame_rate", video_stream.get("r_frame_rate", "0/1"))
    fps = 0.0
    if "/" in fps_str:
        num, den = fps_str.split("/")
        if float(den) != 0:
            fps = float(num) / float(den)
    else:
        fps = float(fps_str)

    return VideoMeta(
        path=video_path.resolve(),
        filename=video_path.name,
        duration_sec=duration,
        fps=fps,
        width=video_stream.get("width", 0),
        height=video_stream.get("height", 0),
        codec=video_stream.get("codec_name", ""),
        has_audio=audio_stream is not None,
    )


def extract_audio(
    video_path: str | Path,
    output_path: str | Path | None = None,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Path:
    """
    Extract audio track from video as WAV.

    Parameters
    ----------
    video_path : Path to the input video.
    output_path : Where to write the WAV. Defaults to ``temp/<video_stem>.wav``.
    sample_rate : Output sample rate in Hz.
    channels : 1 = mono, 2 = stereo. Whisper prefers mono.

    Returns
    -------
    Path to the extracted WAV file.
    """
    _check_ffmpeg()
    video_path = Path(video_path)

    if output_path is None:
        temp_dir = Path("temp")
        temp_dir.mkdir(exist_ok=True)
        output_path = temp_dir / f"{video_path.stem}_audio.wav"
    else:
        output_path = Path(output_path)

    # ffmpeg: discard video, force mono, resample, output WAV
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",                        # no video
        "-ac", str(channels),         # audio channels
        "-ar", str(sample_rate),      # sample rate
        "-f", "wav",
        "-loglevel", "error",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise AudioExtractionError(
            f"ffmpeg audio extraction failed:\n{result.stderr}"
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise AudioExtractionError("Extracted audio file is empty.")

    return output_path
