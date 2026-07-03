"""Post-process ASR transcripts to fix common Whisper phonetic errors using LLM."""

from models import TranscriptSegment

FIX_PROMPT = """You are fixing ASR transcription errors in Chinese speech-to-text output.
Whisper often makes phonetic errors (homophones, similar-sounding characters).
Fix these errors while keeping the original meaning.

Rules:
- Fix obvious homophone errors (e.g. 軍線→均線, 商典→上點, 長停→漲停, 死軍→死叉)
- Fix financial/stock terms that Whisper commonly gets wrong
- Keep the speaking style and rhythm
- Do NOT rewrite or summarize — only fix errors
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
