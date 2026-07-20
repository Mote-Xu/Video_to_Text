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
    # Track text frequency across frames for UI element filtering
    text_frame_count: dict[str, int] = {}
    all_raw: list[OcrResult] = []

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

            result = OcrResult(
                text=text.strip(),
                confidence=round(float(confidence), 3),
                frame_index=kf.index,
                timestamp_sec=kf.timestamp_sec,
            )
            all_raw.append(result)

            # Count per-frame occurrence (for UI filtering)
            norm = text.strip()
            if key[0] not in text_frame_count:
                text_frame_count[key[0]] = set()
            text_frame_count[key[0]].add(kf.index)

    # --- Post-process: filter UI elements that appear in too many frames ---
    total_frames = len(keyframes)
    ui_threshold = max(3, total_frames * 0.3)  # text in >30% of frames = UI noise
    ui_texts: set[str] = set()
    for txt, frames in text_frame_count.items():
        if len(frames) >= ui_threshold:
            ui_texts.add(txt)

    # Also filter common UI keywords (prefix match)
    ui_prefixes = ("梗百科", "键政梗百科", "毒奶", "马超",
                   "功能", "报价", "资讯", "工具", "帮助", "发现",
                   "分时", "统计", "画线", "+自选", "返回")
    ui_contains = ("梗百科bot", "梗百科b", "bilbili", "bilibili",
                   "Lll", "bbl ", "FIO", "Doi")
    for r in all_raw:
        if r.text in ui_texts:
            continue
        if any(r.text.startswith(p) for p in ui_prefixes):
            continue
        if any(c in r.text for c in ui_contains):
            continue
        if len(r.text) <= 1:  # skip single-character fragments
            continue
        # Skip pure numbers or timestamps (e.g. "00:06;20", "145|")
        stripped = r.text.replace(":", "").replace(";", "").replace("|", "").replace(" ", "").replace(".", "")
        if stripped.isdigit() and len(stripped) >= 3:
            continue
        results.append(r)

    if ui_texts:
        print(f"  OCR filter: removed {len(ui_texts)} UI elements, "
              f"kept {len(results)}/{len(all_raw)} detections")

    return results
