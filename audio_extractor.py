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
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
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

    # Strategy 0: Extract raw AAC, then convert (handles partially corrupt streams)
    raw_aac = output_path.with_suffix(".aac")
    raw_result = subprocess.run(
        ["ffmpeg", "-y", "-err_detect", "ignore_err",
         "-i", str(video_path), "-vn", "-acodec", "copy",
         "-loglevel", "error", str(raw_aac)],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    if raw_result.returncode == 0 and raw_aac.exists() and raw_aac.stat().st_size > 0:
        # Convert raw AAC to WAV — accept partial success
        wav_result = subprocess.run(
            ["ffmpeg", "-y", "-err_detect", "ignore_err",
             "-i", str(raw_aac), "-ac", str(channels), "-ar", str(sample_rate),
             "-c:a", "pcm_s16le", "-f", "wav",
             "-loglevel", "error", str(output_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        raw_aac.unlink(missing_ok=True)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path  # partial is better than nothing

    # Strategy 1: pcm_s16le with error ignoring
    result = subprocess.run(
        ["ffmpeg", "-y", "-err_detect", "ignore_err",
         "-i", str(video_path), "-vn", "-ac", str(channels), "-ar", str(sample_rate),
         "-c:a", "pcm_s16le", "-f", "wav",
         "-loglevel", "error", str(output_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    # Strategy 2: with corrupt frame discarding
    result = subprocess.run(
        ["ffmpeg", "-y", "-err_detect", "ignore_err",
         "-fflags", "+genpts+discardcorrupt",
         "-i", str(video_path), "-vn", "-ac", str(channels), "-ar", str(sample_rate),
         "-c:a", "pcm_s16le", "-f", "wav",
         "-loglevel", "error", str(output_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    raise AudioExtractionError(
        f"All audio extraction strategies failed:\n{result.stderr[:500]}"
    )
