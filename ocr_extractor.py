"""OCR text extraction from video keyframes using EasyOCR or Mote Sense remote GPU."""

import io
import json
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PIL import Image

import requests

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


def _ocr_frame_remote(image_path: Path, mote_sense_url: str) -> list[dict]:
    """Send a single keyframe image to Mote Sense /ocr for GPU-accelerated OCR.

    Returns list of {"text": str, "confidence": float, "bbox": [[x,y]*4], "image_size": [w,h]}.
    """
    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f, "image/" + image_path.suffix.lstrip("."))}
        try:
            resp = requests.post(mote_sense_url, files=files, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise OcrError(f"Mote Sense unreachable at {mote_sense_url}: {e}")

    data = resp.json()
    if data.get("status") != "success":
        raise OcrError(f"Mote Sense returned error: {data}")

    blocks = data.get("blocks", [])
    image_size = data.get("image_size")

    return [
        {
            "text": b["text"],
            "confidence": b["confidence"],
            "bbox": b["bbox"],
            "image_size": image_size,
        }
        for b in blocks
    ]


def _filter_ui_noise(
    raw_results: list[OcrResult],
    text_frame_count: dict[str, set[int]],
    total_frames: int,
) -> list[OcrResult]:
    """Filter UI elements that appear in too many frames, plus known UI keywords."""
    ui_threshold = max(3, total_frames * 0.3)
    ui_texts: set[str] = set()
    for txt, frames in text_frame_count.items():
        if len(frames) >= ui_threshold:
            ui_texts.add(txt)

    ui_prefixes = ("梗百科", "键政梗百科", "毒奶", "马超",
                   "功能", "报价", "资讯", "工具", "帮助", "发现",
                   "分时", "统计", "画线", "+自选", "返回")
    ui_contains = ("梗百科bot", "梗百科b", "bilbili", "bilibili",
                   "Lll", "bbl ", "FIO", "Doi")

    filtered: list[OcrResult] = []
    for r in raw_results:
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
        # Spatial ROI: discard text in top/bottom 5% (system UI / progress bars)
        if r.bbox and r.image_size:
            w, h = r.image_size
            y_min = min(p[1] for p in r.bbox)
            y_max = max(p[1] for p in r.bbox)
            if y_max < h * 0.05 or y_min > h * 0.95:
                continue
        filtered.append(r)

    if ui_texts:
        print(f"  OCR filter: removed {len(ui_texts)} UI elements, "
              f"kept {len(filtered)}/{len(raw_results)} detections")

    return filtered


def _run_ocr_remote(
    keyframes: list[KeyFrame],
    mote_sense_url: str,
    conf_threshold: float = 0.5,
) -> list[OcrResult]:
    """Run OCR via Mote Sense remote GPU for a batch of keyframes."""
    seen_texts: set[tuple[str, int]] = set()
    text_frame_count: dict[str, set[int]] = {}
    all_raw: list[OcrResult] = []
    total = len(keyframes)
    failed = 0

    # Filter out missing frames, keep index for ordering
    valid = [(i, kf) for i, kf in enumerate(keyframes) if kf.image_path.exists()]

    def _process_one(idx: int, kf: KeyFrame):
        """Process a single frame — runs in thread pool."""
        try:
            detections = _ocr_frame_remote(kf.image_path, mote_sense_url)
            return idx, kf, detections
        except OcrError as e:
            print(f"  OCR remote [{idx+1}/{total}] {kf.image_path.name}: FAILED — {e}")
            return idx, kf, None

    # max_workers=2 matches Mote Sense concurrency limit
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(_process_one, i, kf): i for i, kf in valid}
        for future in as_completed(futures):
            idx, kf, detections = future.result()
            if detections is None:
                failed += 1
                continue

            for d in detections:
                text = d["text"]
                conf = d["confidence"]
                if conf < conf_threshold or not text:
                    continue

                key = (text, kf.index)
                if key in seen_texts:
                    continue
                seen_texts.add(key)

                result = OcrResult(
                    text=text,
                    confidence=round(float(conf), 3),
                    frame_index=kf.index,
                    timestamp_sec=kf.timestamp_sec,
                    bbox=d.get("bbox"),
                    image_size=d.get("image_size"),
                )
                all_raw.append(result)

                if text not in text_frame_count:
                    text_frame_count[text] = set()
                text_frame_count[text].add(kf.index)

    # Apply UI element filtering
    results = _filter_ui_noise(all_raw, text_frame_count, total)

    if failed:
        print(f"  OCR remote: {len(results)} detections from {total - failed}/{total} frames ({failed} failed)")
    else:
        print(f"  OCR remote: {len(results)} detections from {total} frames via Mote Sense GPU")

    return results


def run_ocr(
    keyframes: list[KeyFrame],
    lang: str = "ch_sim",
    use_gpu: bool = False,
    conf_threshold: float = 0.5,
    engine: str = "easyocr",
    mote_sense_url: str = "http://100.118.10.0:3800/ocr",
) -> list[OcrResult]:
    """
    Run OCR on a list of keyframes.

    Parameters
    ----------
    keyframes : KeyFrame objects with image paths.
    lang : Language code for EasyOCR. Ignored when engine="mote_sense".
    use_gpu : Whether to use GPU for local EasyOCR.
    conf_threshold : Minimum confidence to keep a result.
    engine : "easyocr" (local) or "mote_sense" (remote GPU via mote-home).
    mote_sense_url : Mote Sense API endpoint (only used when engine="mote_sense").

    Returns
    -------
    List of OcrResult with text, confidence, frame index, and timestamp.
    """
    if not keyframes:
        return []

    if engine == "mote_sense":
        return _run_ocr_remote(keyframes, mote_sense_url, conf_threshold)

    # ── Local EasyOCR path ──
    lang_list = [l.strip() for l in lang.split(",") if l.strip()]
    if not lang_list:
        lang_list = ["ch_sim", "en"]

    reader = _get_ocr(lang_list=lang_list)

    results: list[OcrResult] = []
    seen_texts: set[tuple[str, int]] = set()
    # Track text frequency across frames for UI element filtering
    text_frame_count: dict[str, set[int]] = {}
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

    # Apply UI element filtering (shared logic)
    results = _filter_ui_noise(all_raw, text_frame_count, len(keyframes))

    return results
