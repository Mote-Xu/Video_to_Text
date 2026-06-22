"""OCR text extraction from video keyframes using PaddleOCR."""

from pathlib import Path

from models import KeyFrame, OcrResult


class OcrError(Exception):
    """Raised when OCR processing fails."""


# Lazy-loaded OCR instance
_ocr = None


def _get_ocr(lang: str = "ch", use_gpu: bool = False):
    """Return a cached PaddleOCR instance."""
    global _ocr
    if _ocr is None:
        try:
            from paddleocr import PaddleOCR
            _ocr = PaddleOCR(lang=lang, use_gpu=use_gpu, show_log=False)
        except ImportError:
            raise OcrError(
                "PaddleOCR not installed. Install with:\n"
                "  pip install paddlepaddle paddleocr"
            )
    return _ocr


def run_ocr(
    keyframes: list[KeyFrame],
    lang: str = "ch",
    use_gpu: bool = False,
    conf_threshold: float = 0.5,
) -> list[OcrResult]:
    """
    Run OCR on a list of keyframes.

    Parameters
    ----------
    keyframes : KeyFrame objects with image paths.
    lang : PaddleOCR language code. "ch" = Chinese + English.
    use_gpu : Whether to use GPU (may conflict with Whisper VRAM).
    conf_threshold : Minimum confidence to keep a result.

    Returns
    -------
    List of OcrResult with text, confidence, frame index, and timestamp.
    """
    if not keyframes:
        return []

    ocr = _get_ocr(lang=lang, use_gpu=use_gpu)

    results: list[OcrResult] = []
    seen_texts: set[tuple[str, int]] = set()  # dedup: (text, frame_index)

    for kf in keyframes:
        if not kf.image_path.exists():
            continue

        try:
            raw = ocr.ocr(str(kf.image_path))
        except Exception as e:
            raise OcrError(f"OCR failed on {kf.image_path.name}: {e}")

        if raw is None or raw[0] is None:
            continue

        for detection in raw[0]:
            # detection = [bbox, (text, confidence)]
            bbox = detection[0]  # list of 4 points
            text_info = detection[1]
            text = text_info[0]
            confidence = text_info[1]

            if confidence < conf_threshold:
                continue
            if not text.strip():
                continue

            # Simple dedup: same text in same frame
            key = (text.strip(), kf.index)
            if key in seen_texts:
                continue
            seen_texts.add(key)

            results.append(OcrResult(
                text=text.strip(),
                confidence=round(float(confidence), 3),
                frame_index=kf.index,
                timestamp_sec=kf.timestamp_sec,
            ))

    return results
