"""OCR text extraction from video keyframes using EasyOCR."""

import numpy as np
from pathlib import Path
from PIL import Image

from models import KeyFrame, OcrResult


class OcrError(Exception):
    """Raised when OCR processing fails."""


# Lazy-loaded OCR instance
_ocr = None


def _get_ocr(lang_list: list[str] | None = None):
    """Return a cached EasyOCR Reader instance."""
    global _ocr
    if _ocr is None:
        try:
            import easyocr
            langs = lang_list or ["ch_sim", "en"]
            _ocr = easyocr.Reader(langs, gpu=False, verbose=False)
        except ImportError:
            raise OcrError(
                "EasyOCR not installed. Install with:\n"
                "  pip install easyocr"
            )
    return _ocr


def run_ocr(
    keyframes: list[KeyFrame],
    lang: str = "ch_sim",
    use_gpu: bool = False,
    conf_threshold: float = 0.5,
) -> list[OcrResult]:
    """
    Run OCR on a list of keyframes using EasyOCR.

    Parameters
    ----------
    keyframes : KeyFrame objects with image paths.
    lang : Language code. "ch_sim" = Simplified Chinese, also supports "en", "ja", etc.
           Multiple languages can be comma-separated: "ch_sim,en".
    use_gpu : Whether to use GPU. Default False (CPU is fast enough for EasyOCR).
    conf_threshold : Minimum confidence to keep a result.

    Returns
    -------
    List of OcrResult with text, confidence, frame index, and timestamp.
    """
    if not keyframes:
        return []

    lang_list = [l.strip() for l in lang.split(",") if l.strip()]
    if not lang_list:
        lang_list = ["ch_sim", "en"]

    reader = _get_ocr(lang_list=lang_list)

    results: list[OcrResult] = []
    seen_texts: set[tuple[str, int]] = set()

    for kf in keyframes:
        if not kf.image_path.exists():
            continue

        try:
            # Use PIL to read image (handles Unicode paths on Windows)
            img = Image.open(kf.image_path).convert("RGB")
            img_np = np.array(img)
            detections = reader.readtext(img_np)
        except Exception as e:
            raise OcrError(f"OCR failed on {kf.image_path.name}: {e}")

        for detection in detections:
            # EasyOCR returns: (bbox, text, confidence)
            bbox, text, confidence = detection

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
