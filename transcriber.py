"""Speech-to-text transcription using faster-whisper."""

import time
from pathlib import Path

from models import TranscriptSegment


class TranscriptionError(Exception):
    """Raised when ASR transcription fails."""


def transcribe(
    audio_path: str | Path,
    model_size: str = "small",
    device: str = "cuda",
    compute_type: str = "float16",
    language: str | None = None,
    beam_size: int = 5,
    vad_filter: bool = True,
    word_timestamps: bool = True,
) -> list[TranscriptSegment]:
    """
    Transcribe an audio file using faster-whisper.

    Parameters
    ----------
    audio_path : Path to WAV audio file.
    model_size : Whisper model size (tiny/base/small/medium).
    device : "cuda" or "cpu".
    compute_type : "float16" / "int8_float16" / "int8".
    language : Language code ("zh", "en", ...) or None for auto-detect.
    beam_size : Beam size for decoding.
    vad_filter : Enable Silero VAD to filter silence.
    word_timestamps : Return word-level timestamps.

    Returns
    -------
    List of TranscriptSegment with timestamps.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    from faster_whisper import WhisperModel

    # Workaround: if compute_type is float16 but GPU doesn't support it,
    # try int8_float16 instead.
    effective_compute = compute_type
    if device == "cuda" and compute_type == "float16":
        try:
            import torch
            if not torch.cuda.is_available():
                raise TranscriptionError("CUDA requested but not available.")
            # Check compute capability — float16 needs >= 7.0
            cap = torch.cuda.get_device_capability(0)
            if cap[0] < 7:
                effective_compute = "int8_float16"
        except Exception:
            effective_compute = "int8_float16"

    # fmt: off
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=effective_compute,
    )
    # fmt: on

    # Run transcription
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
    )

    detected_lang = info.language
    results: list[TranscriptSegment] = []

    for seg in segments:
        results.append(TranscriptSegment(
            start_sec=round(seg.start, 3),
            end_sec=round(seg.end, 3),
            text=seg.text.strip(),
            confidence=round(seg.avg_logprob, 3),
            language=detected_lang,
        ))

    return results
