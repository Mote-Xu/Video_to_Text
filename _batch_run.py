"""Batch process all videos in videos/2026-06-25/"""
import subprocess, sys, time
from pathlib import Path

video_dir = Path("videos/2026-06-25")
videos = sorted(video_dir.glob("*.mp4"))

print(f"Found {len(videos)} videos\n")
failed = []

for i, v in enumerate(videos, 1):
    print(f"\n{'='*60}")
    print(f"[{i}/{len(videos)}] {v.name}")
    print(f"{'='*60}")

    start = time.perf_counter()
    result = subprocess.run(
        [
            sys.executable, "main.py",
            str(v),
            "--model", "tiny",
            "--interval", "8",
            "--language", "zh",
            "--device", "cpu",
            "--skip-vision",
        ],
        capture_output=False,  # show progress
        timeout=600,
    )

    elapsed = time.perf_counter() - start
    if result.returncode == 0:
        print(f"✅ Done in {elapsed:.0f}s")
    else:
        print(f"❌ Failed in {elapsed:.0f}s (exit {result.returncode})")
        failed.append(v.name)

print(f"\n{'='*60}")
print(f"Batch complete: {len(videos) - len(failed)}/{len(videos)} succeeded")
if failed:
    print(f"Failed: {failed}")
