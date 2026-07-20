"""Speech-to-text transcription using faster-whisper or DashScope Paraformer."""

import json
import time
from pathlib import Path

import requests

from models import TranscriptSegment


class TranscriptionError(Exception):
    """Raised when ASR transcription fails."""


def transcribe(
    audio_path: str | Path,
    engine: str = "faster-whisper",
    model_size: str = "small",
    device: str = "cuda",
    compute_type: str = "float16",
    language: str | None = None,
    beam_size: int = 5,
    vad_filter: bool = True,
    word_timestamps: bool = True,
    dashscope_model: str = "paraformer-v2",
    dashscope_api_key: str = "",
) -> list[TranscriptSegment]:
    """
    Transcribe an audio file.

    Parameters
    ----------
    audio_path : Path to WAV audio file.
    engine : "faster-whisper" or "dashscope".
    model_size : Whisper model size (tiny/base/small/medium).
    device : "cuda" or "cpu".
    compute_type : "float16" / "int8_float16" / "int8".
    language : Language code ("zh", "en", ...) or None for auto-detect.
    beam_size : Beam size for decoding.
    vad_filter : Enable Silero VAD to filter silence.
    word_timestamps : Return word-level timestamps.
    dashscope_model : DashScope ASR model ID.
    dashscope_api_key : DashScope API key.

    Returns
    -------
    List of TranscriptSegment with timestamps.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if engine == "dashscope":
        return _transcribe_dashscope(audio_path, dashscope_model, dashscope_api_key, language)
    else:
        return _transcribe_whisper(
            audio_path, model_size, device, compute_type,
            language, beam_size, vad_filter, word_timestamps,
        )


# ---------------------------------------------------------------------------
# faster-whisper
# ---------------------------------------------------------------------------

def _transcribe_whisper(
    audio_path: Path,
    model_size: str,
    device: str,
    compute_type: str,
    language: str | None,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
) -> list[TranscriptSegment]:
    """Transcribe using local faster-whisper."""
    from faster_whisper import WhisperModel

    effective_compute = compute_type
    if compute_type == "float16":
        if device == "cpu":
            effective_compute = "int8"
        elif device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    raise TranscriptionError("CUDA requested but not available.")
                cap = torch.cuda.get_device_capability(0)
                if cap[0] < 7:
                    effective_compute = "int8_float16"
            except Exception:
                effective_compute = "int8_float16"

    model = WhisperModel(model_size, device=device, compute_type=effective_compute)

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


# ---------------------------------------------------------------------------
# DashScope Paraformer (file transcription API)
# ---------------------------------------------------------------------------

DASHSCOPE_ASR_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
DASHSCOPE_FILE_UPLOAD_URL = "https://dashscope.aliyuncs.com/api/v1/files"
DASHSCOPE_FILE_DETAIL_URL = "https://dashscope.aliyuncs.com/api/v1/files/{file_id}"
POLL_INTERVAL_SEC = 5
MAX_POLL_SEC = 600  # 10 min timeout for long audio


def _transcribe_dashscope(
    audio_path: Path,
    model: str,
    api_key: str,
    language: str | None,
) -> list[TranscriptSegment]:
    """Transcribe using DashScope Paraformer file transcription API.

    1. Upload audio to DashScope Files API
    2. Get the file's public URL
    3. Submit to async ASR transcription
    4. Poll for results
    """
    if not api_key:
        raise TranscriptionError(
            "DASHSCOPE_API_KEY not set. Add it to .env or environment."
        )

    headers = {"Authorization": f"Bearer {api_key}"}

    # --- Step 1: Upload audio file ---
    print(f"  Uploading audio to DashScope ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)...")
    with open(audio_path, "rb") as f:
        upload_resp = requests.post(
            DASHSCOPE_FILE_UPLOAD_URL,
            headers=headers,
            files={"file": (audio_path.name, f, "audio/wav")},
            timeout=300,
        )

    if upload_resp.status_code != 200:
        raise TranscriptionError(
            f"DashScope file upload failed (HTTP {upload_resp.status_code}): {upload_resp.text[:500]}"
        )

    upload_data = upload_resp.json()
    uploaded = upload_data.get("data", {}).get("uploaded_files", [])
    if not uploaded:
        raise TranscriptionError("DashScope file upload: no files returned")
    file_id = uploaded[0]["file_id"]

    # --- Step 2: Get file URL ---
    file_resp = requests.get(
        DASHSCOPE_FILE_DETAIL_URL.format(file_id=file_id),
        headers=headers,
        timeout=30,
    )
    if file_resp.status_code != 200:
        raise TranscriptionError(
            f"DashScope file detail failed (HTTP {file_resp.status_code}): {file_resp.text[:500]}"
        )

    file_url = file_resp.json().get("data", {}).get("url")
    if not file_url:
        raise TranscriptionError("DashScope file detail: no URL in response")

    # --- Step 3: Submit ASR task ---
    print(f"  Submitting ASR task ({model})...")
    asr_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    asr_body = {
        "model": model,
        "input": {"file_urls": [file_url]},
        "parameters": {
            "format": "wav",
            "sample_rate": 16000,
            "language_hints": [language] if language else ["zh", "en"],
        },
    }

    asr_resp = requests.post(
        DASHSCOPE_ASR_URL,
        json=asr_body,
        headers=asr_headers,
        timeout=60,
    )

    if asr_resp.status_code != 200:
        raise TranscriptionError(
            f"DashScope ASR submit failed (HTTP {asr_resp.status_code}): {asr_resp.text[:500]}"
        )

    task_id = asr_resp.json().get("output", {}).get("task_id")
    if not task_id:
        raise TranscriptionError(
            f"DashScope ASR: no task_id in response: {asr_resp.text[:500]}"
        )

    # --- Step 4: Poll for results ---
    print(f"  Waiting for DashScope ASR (task: {task_id})...")
    elapsed = 0
    while elapsed < MAX_POLL_SEC:
        time.sleep(POLL_INTERVAL_SEC)
        elapsed += POLL_INTERVAL_SEC

        poll_resp = requests.get(
            DASHSCOPE_TASK_URL.format(task_id=task_id),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        if poll_resp.status_code != 200:
            continue

        poll_body = poll_resp.json()
        task_status = poll_body.get("output", {}).get("task_status")

        if task_status == "SUCCEEDED":
            return _fetch_dashscope_transcription(poll_body, api_key)
        elif task_status == "FAILED":
            err = poll_body.get("output", {}).get("message", str(poll_body)[:500])
            raise TranscriptionError(f"DashScope ASR task failed: {err}")

        mins = elapsed // 60
        secs = elapsed % 60
        print(f"  ... still waiting ({mins}m{secs}s)")

    raise TranscriptionError(
        f"DashScope ASR timed out after {MAX_POLL_SEC}s (task: {task_id})"
    )


def _fetch_dashscope_transcription(
    poll_body: dict,
    api_key: str,
) -> list[TranscriptSegment]:
    """
    DashScope stores transcription results in an OSS JSON file.
    The task output contains a `transcription_url` we must download.
    """
    output = poll_body.get("output", {})
    results = output.get("results", [])

    transcription_url = ""
    for r in results:
        # Nested structure: result can have its own 'output' with 'transcription_url'
        inner = r.get("output", r)
        inner_results = inner.get("results", [])
        for ir in inner_results:
            tu = ir.get("transcription_url", "")
            if tu:
                transcription_url = tu
                break
        if not transcription_url:
            transcription_url = r.get("transcription_url", "")
        if transcription_url:
            break

    if not transcription_url:
        # Try to get raw sentences if present (some models return directly)
        segments = _parse_dashscope_results(results)
        if segments:
            return segments
        raise TranscriptionError(
            "DashScope ASR: no transcription_url in task result and no direct sentences"
        )

    # Download the transcription JSON
    print(f"  Downloading transcription...")
    trans_resp = requests.get(transcription_url, timeout=60)
    if trans_resp.status_code != 200:
        raise TranscriptionError(
            f"Failed to download transcription (HTTP {trans_resp.status_code})"
        )

    trans_data = trans_resp.json()
    transcripts = trans_data.get("transcripts", [])

    segments: list[TranscriptSegment] = []
    for t in transcripts:
        for sent in t.get("sentences", []):
            text = sent.get("text", "").strip()
            if not text:
                continue
            segments.append(TranscriptSegment(
                start_sec=round(sent.get("begin_time", 0) / 1000.0, 3),
                end_sec=round(sent.get("end_time", 0) / 1000.0, 3),
                text=text,
                confidence=1.0,
                language="zh",
            ))

    return segments


def _parse_dashscope_results(results: list[dict]) -> list[TranscriptSegment]:
    """Parse DashScope ASR response into TranscriptSegment list (direct mode)."""
    segments: list[TranscriptSegment] = []

    for result in results:
        sentences = result.get("sentences", [])
        for sent in sentences:
            text = sent.get("text", "").strip()
            if not text:
                continue
            segments.append(TranscriptSegment(
                start_sec=round(sent.get("begin_time", 0) / 1000.0, 3),  # ms → s
                end_sec=round(sent.get("end_time", 0) / 1000.0, 3),
                text=text,
                confidence=round(sent.get("confidence", 1.0), 3),
                language="zh",
            ))

    return segments
