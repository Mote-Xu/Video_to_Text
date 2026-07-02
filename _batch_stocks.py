"""Batch re-process all stock videos with small model + fixed parser + AAC fix."""
import subprocess, sys, time, shutil
from pathlib import Path

video_dir = Path("videos/2026-07-01")
videos = sorted(video_dir.glob("*.mp4"))

# Clean old outputs
for v in videos:
    out = Path("outputs/2026-07-01") / v.stem
    if out.exists():
        shutil.rmtree(out)

print(f"Processing {len(videos)} videos\n")
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
            "--model", "small",
            "--interval", "60",
            "--language", "zh",
            "--device", "cpu",
        ],
        capture_output=False,
        timeout=900,
    )

    elapsed = time.perf_counter() - start
    if result.returncode == 0:
        print(f"Done in {elapsed:.0f}s")
    else:
        print(f"FAILED in {elapsed:.0f}s (exit {result.returncode})")
        failed.append(v.name)

print(f"\n{'='*60}")
print(f"Complete: {len(videos) - len(failed)}/{len(videos)} succeeded")
if failed:
    print(f"Failed: {failed}")
