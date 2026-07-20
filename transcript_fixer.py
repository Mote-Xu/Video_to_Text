"""Post-process ASR transcripts: filter hallucinations + fix errors using LLM."""

import re

from models import TranscriptSegment


# ---------------------------------------------------------------------------
# Garbage filter — remove obvious ASR hallucinations before LLM fix
# ---------------------------------------------------------------------------

# Characters that shouldn't appear randomly in Chinese text
_GARBAGE_PATTERNS = [
    re.compile(r"[a-zA-Z]{4,}"),           # 4+ consecutive Latin chars in Chinese segment
    re.compile(r"[0-9]{6,}"),              # 6+ consecutive digits (unlikely in speech)
    re.compile(r"[!@#$%^&*(){}\[\]<>~`]"), # Special symbols
    re.compile(r"[a-z]{2,}\s+[a-z]{2,}"), # Multiple English words
]

# Common words that are OK even with English (e.g. "GDP", "IMF", "OK")
_SAFE_TERMS = {"GDP", "IMF", "CEO", "CFO", "OK", "AI", "VIP", "B站", "UP主",
               "MACD", "KDJ", "RISC", "CPU", "GPU", "DIY", "NBA", "KPI"}


def _looks_like_garbage(text: str) -> bool:
    """Heuristic: does this segment look like an ASR hallucination?"""
    if not text or len(text) < 2:
        return True

    # Count character types
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿' or '　' <= c <= '〿')
    latin_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    total = len(text.replace(" ", ""))

    if total == 0:
        return True

    chinese_ratio = chinese_chars / total if total else 0

    # Pure Latin/ASCII gibberish (no Chinese)
    if chinese_ratio < 0.1 and latin_alpha > 10:
        return True

    # Mixed Chinese+Latin but Latin looks like random letters (not real words)
    if chinese_ratio > 0.1 and latin_alpha > 8:
        # Extract consecutive Latin letter sequences
        latin_runs = re.findall(r'[a-zA-Z]{2,}', text)
        if latin_runs:
            # Check if these look like real words vs random strings
            text_upper = text.upper()
            real_word_count = sum(1 for t in _SAFE_TERMS if t in text_upper)
            # If Latin runs are mostly short (1-3 chars) and scattered, it's likely garbage
            avg_run_len = sum(len(r) for r in latin_runs) / len(latin_runs)
            if real_word_count == 0 and avg_run_len < 4 and len(latin_runs) >= 2:
                return True  # Scattered short Latin fragments = hallucination

    # Ratio of garbage symbols (exclude % which is common in data-heavy speech)
    garbage_chars = sum(1 for c in text if c in "!@#$^&*(){}[]<>~`|")
    if garbage_chars > 3 and garbage_chars / total > 0.05:
        return True

    return False


def filter_garbage(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Remove hallucinated/garble segments before LLM fixing."""
    filtered = []
    removed = 0
    for seg in segments:
        if _looks_like_garbage(seg.text):
            removed += 1
            continue
        filtered.append(seg)
    if removed:
        print(f"  Garbage filter: removed {removed} hallucinated segment(s)")
    return filtered


# ---------------------------------------------------------------------------
# LLM fixer
# ---------------------------------------------------------------------------

FIX_PROMPT = """You are fixing ASR transcription errors in Chinese speech-to-text output.
The ASR engine sometimes makes phonetic errors or mishears technical terms.

Rules:
- Fix obvious homophone errors (e.g. 军线→均线, 战略→战略, 工纪→功绩)
- Fix common ASR substitution patterns in Chinese (misheard characters)
- Fix nonsensical character combinations that sound similar to real words
- Keep the speaking style and rhythm — do NOT rewrite or summarize
- If a segment is already correct, output it unchanged
- Return ONLY the corrected text, one line per segment, with "SEGMENT:" prefix

Input transcript segments (format: [start-end] text):"""


def fix_transcript(
    segments: list[TranscriptSegment],
    api_key: str,
    model: str = "deepseek-chat",
    batch_size: int = 20,
) -> list[TranscriptSegment]:
    """
    Fix common ASR errors using an LLM.

    Steps:
    1. Pre-filter obviously hallucinated/garbled segments
    2. Send remaining segments to DeepSeek for homophone correction

    Parameters
    ----------
    segments : Original transcript segments.
    api_key : DeepSeek or OpenAI-compatible API key.
    model : LLM model ID.
    batch_size : How many segments to send per API call.

    Returns
    -------
    Corrected transcript segments.
    """
    if not segments or not api_key:
        return segments

    # Step 0: Pre-filter garbage
    segments = filter_garbage(segments)
    if not segments:
        return segments

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    fixed: list[TranscriptSegment] = []

    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]

        # Format segments for the prompt
        segment_text = "\n".join(
            f"SEGMENT:[{s.start_sec:.1f}-{s.end_sec:.1f}] {s.text}"
            for s in batch
        )

        full_prompt = f"{FIX_PROMPT}\n\n{segment_text}"

        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=len(segment_text) * 2,
                temperature=0.1,
                messages=[{"role": "user", "content": full_prompt}],
            )
            raw = response.choices[0].message.content
        except Exception:
            # On failure, keep originals
            fixed.extend(batch)
            continue

        # Parse corrected segments
        corrected_lines: dict[int, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("SEGMENT:") and "] " in line:
                try:
                    ts_part = line.split("] ", 1)[0].replace("SEGMENT:", "").strip()
                    text_part = line.split("] ", 1)[1].strip()
                    corrected_lines[len(corrected_lines)] = text_part
                except (ValueError, IndexError):
                    pass

        # Match corrected text back to original segments
        for i, seg in enumerate(batch):
            text = corrected_lines.get(i, seg.text)
            fixed.append(TranscriptSegment(
                start_sec=seg.start_sec,
                end_sec=seg.end_sec,
                text=text,
                confidence=seg.confidence,
                language=seg.language,
            ))

    return fixed
