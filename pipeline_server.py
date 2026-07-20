#!/usr/bin/env python3
"""
HTTP pipeline server — Stella's execution engine.

Stella is the driver: she decides parameters based on video content.
This server is the engine: receives orders, runs pipeline, reports back.

Run:
  python pipeline_server.py
  python pipeline_server.py --port 8940 --token my-token
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent

# Track running/completed tasks
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


class PipelineHandler(BaseHTTPRequestHandler):
    server_token: str = ""
    server_port: int = 8940

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}", flush=True)

    def _check_auth(self) -> bool:
        if not self.server_token:
            return True
        expected = f"Bearer {self.server_token}"
        if self.headers.get("Authorization", "") != expected:
            self._json(403, {"error": "unauthorized"})
            return False
        return True

    def _json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    # ── GET ──────────────────────────────────────────────────────────

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self._json(200, {"status": "ok", "project": str(PROJECT_ROOT)})

        elif path == "/status":
            if not self._check_auth():
                return
            with _tasks_lock:
                tasks_copy = dict(_tasks)
            self._json(200, {"tasks": tasks_copy})

        elif path == "/videos":
            if not self._check_auth():
                return
            vdir = PROJECT_ROOT / "videos"
            vlist = []
            if vdir.exists():
                for f in sorted(vdir.rglob("*.mp4")):
                    vlist.append({
                        "path": str(f.relative_to(PROJECT_ROOT)),
                        "name": f.name,
                        "size_mb": round(f.stat().st_size / 1024 / 1024, 1),
                    })
            self._json(200, {"videos": vlist})

        else:
            self._json(404, {"error": "not found"})

    # ── POST ─────────────────────────────────────────────────────────

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/process":
            if not self._check_auth():
                return
            self._handle_process()
        elif path == "/process-batch":
            if not self._check_auth():
                return
            self._handle_batch()
        else:
            self._json(404, {"error": "not found"})

    def _handle_process(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        video_path = body.get("video", "")
        if not video_path:
            self._json(400, {"error": "missing 'video' field"})
            return

        # Resolve video path
        video_full = PROJECT_ROOT / video_path
        if not video_full.exists():
            video_full = PROJECT_ROOT / "videos" / video_path
        if not video_full.exists():
            self._json(404, {
                "error": "video not found",
                "tried": [str(PROJECT_ROOT / video_path), str(PROJECT_ROOT / "videos" / video_path)],
            })
            return

        # Build command from Stella's parameters
        cmd = self._build_command(video_full, body)

        # Register task
        task_id = str(uuid.uuid4())[:8]
        with _tasks_lock:
            _tasks[task_id] = {
                "id": task_id,
                "video": video_full.name,
                "status": "running",
                "started_at": time.strftime("%H:%M:%S"),
                "params": {k: v for k, v in body.items() if k != "video"},
            }

        # Respond immediately
        self._json(202, {
            "task_id": task_id,
            "status": "accepted",
            "video": str(video_full),
            "message": f"Processing started: {video_full.name}",
            "check_status": f"GET /status",
        })

        # Run in background
        threading.Thread(
            target=self._run_pipeline,
            args=(task_id, cmd, video_full),
            daemon=True,
        ).start()

    def _handle_batch(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        directory = body.get("directory", "")
        if not directory:
            self._json(400, {"error": "missing 'directory' field"})
            return

        # Resolve directory
        dir_full = PROJECT_ROOT / directory
        if not dir_full.exists():
            dir_full = PROJECT_ROOT / "videos" / directory
        if not dir_full.exists() or not dir_full.is_dir():
            self._json(404, {"error": "directory not found", "tried": str(dir_full)})
            return

        # Find all mp4 files recursively
        videos = sorted(dir_full.rglob("*.mp4"))
        if not videos:
            self._json(404, {"error": "no .mp4 files found", "dir": str(dir_full)})
            return

        task_ids = []
        for vf in videos:
            task_id = str(uuid.uuid4())[:8]
            cmd = self._build_command(vf, body)
            with _tasks_lock:
                _tasks[task_id] = {
                    "id": task_id,
                    "video": vf.name,
                    "status": "queued",
                    "started_at": time.strftime("%H:%M:%S"),
                    "params": {k: v for k, v in body.items() if k not in ("video", "directory")},
                }
            task_ids.append(task_id)

        # Respond immediately
        self._json(202, {
            "status": "accepted",
            "count": len(videos),
            "task_ids": task_ids,
            "message": f"Batch started: {len(videos)} videos",
            "check_status": "GET /status",
        })

        # Process sequentially in background (to avoid CPU/RAM overload)
        def _batch_runner():
            for vf, task_id in zip(videos, task_ids):
                cmd = self._build_command(vf, body)
                self._run_pipeline(task_id, cmd, vf)

        threading.Thread(target=_batch_runner, daemon=True).start()

    def _build_command(self, video_full: Path, body: dict) -> list[str]:
        """Build pipeline CLI command from Stella's parameters."""
        cmd = [
            sys.executable, str(PROJECT_ROOT / "main.py"),
            str(video_full),
            "--scene-mode", "interval",
            "-o", str(PROJECT_ROOT / "outputs"),
        ]

        # ── Stella-controllable parameters ──

        # ASR engine
        asr_engine = body.get("asr_engine", "")
        if asr_engine:
            cmd += ["--asr-engine", asr_engine]

        # Keyframe interval
        interval = body.get("interval", 20)
        cmd += ["--interval", str(interval)]

        # Toggles
        if body.get("skip_vision"):
            cmd.append("--skip-vision")
        if body.get("skip_ocr"):
            cmd.append("--skip-ocr")
        if body.get("skip_asr"):
            cmd.append("--skip-asr")

        # Model
        if body.get("whisper_model"):
            cmd += ["--model", body["whisper_model"]]

        # Device
        if body.get("device"):
            cmd += ["--device", body["device"]]

        return cmd

    def _run_pipeline(self, task_id: str, cmd: list[str], video_path: Path):
        """Run pipeline and update task status."""
        print(f"\n{'='*60}")
        print(f"[{task_id}] Pipeline: {video_path.name}")
        print(f"[{task_id}] {' '.join(cmd)}")
        print(f"{'='*60}\n", flush=True)

        start = time.time()

        try:
            env = {**__import__("os").environ}
            ffmpeg_bin = Path("C:/anaconda3/envs/Video_to_Text/Library/bin")
            if ffmpeg_bin.exists():
                env["PATH"] = str(ffmpeg_bin) + ";" + env.get("PATH", "")

            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                timeout=7200, cwd=str(PROJECT_ROOT), env=env,
            )
            stdout = result.stdout
            stderr = result.stderr
            success = result.returncode == 0

            # Extract output path from pipeline stdout
            output_md = ""
            for line in stdout.splitlines():
                if "Markdown:" in line:
                    output_md = line.split("Markdown:")[-1].strip()
                    break

            elapsed = round(time.time() - start, 1)
            with _tasks_lock:
                _tasks[task_id].update({
                    "status": "done" if success else "failed",
                    "elapsed_sec": elapsed,
                    "report_path": output_md,
                    "exit_code": result.returncode,
                })

            print(stdout, flush=True)
            if not success:
                print(f"[{task_id}] ERROR: {stderr[-500:]}", flush=True)
            print(f"[{task_id}] Done in {elapsed}s — {output_md or 'no report'}", flush=True)

        except Exception as e:
            elapsed = round(time.time() - start, 1)
            with _tasks_lock:
                _tasks[task_id].update({
                    "status": "error",
                    "elapsed_sec": elapsed,
                    "error": str(e),
                })
            print(f"[{task_id}] CRASH: {e}", flush=True)


# ── Main ─────────────────────────────────────────────────────────────

def find_tailscale_ip() -> str:
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "0.0.0.0"


def main():
    p = argparse.ArgumentParser(description="Video-to-Text Pipeline Server (Stella's engine)")
    p.add_argument("--port", type=int, default=8940)
    p.add_argument("--host", type=str, default=None,
                   help="Bind address (default: Tailscale IP auto-detect)")
    p.add_argument("--token", type=str, default="",
                   help="Bearer token for auth (empty = no auth on Tailscale only)")
    args = p.parse_args()

    host = args.host or find_tailscale_ip()
    PipelineHandler.server_token = args.token

    server = HTTPServer((host, args.port), PipelineHandler)

    print(f"Pipeline server: http://{host}:{args.port}")
    print(f"   Auth: {'token' if args.token else 'open (Tailscale only)'}")
    print(f"   Project: {PROJECT_ROOT}")
    print(f"\n   Stella calls:")
    print(f"     GET  /health  — health check")
    print(f"     GET  /videos  — list videos")
    print(f"     GET  /status  — check task status")
    print(f"     POST /process — start pipeline")
    print(f"\n   Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
