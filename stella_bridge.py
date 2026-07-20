"""Stella Bridge — fetch video analysis from Stella (mote-home server).

Stella writes analysis JSON to /mnt/data/video-analysis/{video_id}.json.
This module pulls those files to the local pipeline via SSH or local file.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Default locations
STELLA_REMOTE_DIR = "/mnt/data/video-analysis"
STELLA_LOCAL_CACHE = Path("temp/stella_cache")
STELLA_DEFAULT_HOST = "mote"  # SSH alias from ~/.ssh/config


class StellaBridgeError(Exception):
    """Raised when Stella bridge operations fail."""


def fetch_stella_analysis(
    video_id: str,
    host: str = STELLA_DEFAULT_HOST,
    remote_dir: str = STELLA_REMOTE_DIR,
    cache_dir: Path | None = None,
) -> dict | None:
    """
    Fetch Stella's video analysis from mote-home.

    Tries in order:
    1. Local cache (if previously fetched)
    2. Local file (if Stella wrote to a shared path)
    3. SSH pull from mote-home

    Parameters
    ----------
    video_id : B站 AV/BV number or video filename stem.
    host : SSH host alias (default: "mote").
    remote_dir : Remote directory on mote-home.
    cache_dir : Local cache directory.

    Returns
    -------
    Parsed analysis dict, or None if not found.
    """
    cache = cache_dir or STELLA_LOCAL_CACHE
    cache.mkdir(parents=True, exist_ok=True)

    json_filename = f"{video_id}.json"
    local_path = cache / json_filename

    # 1. Check cache
    if local_path.exists():
        try:
            return json.loads(local_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Check if there's a local copy (e.g. synced via Taildrop)
    alt_paths = [
        Path(f"temp/{json_filename}"),
        Path(f"outputs/_stella/{json_filename}"),
    ]
    for alt in alt_paths:
        if alt.exists():
            try:
                data = json.loads(alt.read_text(encoding="utf-8"))
                _save_cache(local_path, data)
                return data
            except (json.JSONDecodeError, OSError):
                continue

    # 3. SSH pull from mote-home
    try:
        data = _ssh_pull(host, f"{remote_dir}/{json_filename}")
        if data:
            _save_cache(local_path, data)
            return data
    except StellaBridgeError as e:
        print(f"  Stella bridge: SSH pull failed — {e}")

    return None


def _ssh_pull(host: str, remote_path: str) -> dict | None:
    """Pull a JSON file from remote server via SSH."""
    # Check if file exists
    result = subprocess.run(
        ["ssh", host, "test", "-f", remote_path, "&&", "echo", "EXISTS", "||", "echo", "NOT_FOUND"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    if "NOT_FOUND" in result.stdout:
        return None

    # Read file contents
    result = subprocess.run(
        ["ssh", host, "cat", remote_path],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    if result.returncode != 0:
        raise StellaBridgeError(f"SSH read failed: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise StellaBridgeError(f"Invalid JSON from Stella: {e}")


def _save_cache(path: Path, data: dict) -> None:
    """Save analysis data to local cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_analysis(stella_data: dict | None, local_profile: dict) -> dict:
    """
    Merge Stella's analysis with local content analysis.
    Stella's data takes priority for qualitative fields (prompt, style_notes).
    Local data is fallback for API-derived fields (tags, title).
    """
    if not stella_data:
        return local_profile

    merged = dict(local_profile)  # start with local

    # Stella overrides for classification
    if stella_data.get("video_type"):
        merged["video_type"] = stella_data["video_type"]
    if stella_data.get("video_type_label"):
        merged["video_type_label"] = stella_data["video_type_label"]

    # Stella provides richer context
    if stella_data.get("style_notes"):
        merged["style_notes"] = stella_data["style_notes"]
    if stella_data.get("comments_summary"):
        merged["comments_summary"] = stella_data["comments_summary"]
    if stella_data.get("key_terms"):
        merged["key_terms"] = stella_data["key_terms"]

    # Merge topics: Stella + local, deduplicated
    stella_topics = stella_data.get("topics", [])
    local_topics = merged.get("topics", [])
    merged["topics"] = list(dict.fromkeys(stella_topics + local_topics))[:8]

    # Use Stella's suggested prompt if available
    if stella_data.get("suggested_prompt"):
        merged["suggested_prompt"] = stella_data["suggested_prompt"]
        merged["prompt_source"] = "stella"

    # Mark data source
    merged["stella_enriched"] = True
    merged["stella_analyzed_at"] = stella_data.get("analyzed_at", "")

    return merged
