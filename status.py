#!/usr/bin/env python3
"""Pipeline status — CLI + Web dashboard.  python status.py --serve  →  :8940"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

PROJECT_ROOT = Path(__file__).resolve().parent
VIDEOS_DIR = PROJECT_ROOT / "videos"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# ── Data ────────────────────────────────────────────────────────────

def find_all_videos() -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    if not VIDEOS_DIR.exists():
        return mapping
    for f in VIDEOS_DIR.rglob("*"):
        if f.suffix.lower() not in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv"}:
            continue
        rel = f.relative_to(VIDEOS_DIR)
        key = str(rel.parent / rel.stem).replace("\\", "/")
        mapping[key] = f
    return mapping


def find_output_dirs() -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    if not OUTPUTS_DIR.exists():
        return mapping
    for report in OUTPUTS_DIR.rglob("report.md"):
        out_dir = report.parent
        rel = out_dir.relative_to(OUTPUTS_DIR)
        key = str(rel).replace("\\", "/")
        mapping[key] = out_dir
    for kf in OUTPUTS_DIR.rglob("keyframes"):
        out_dir = kf.parent
        rel = out_dir.relative_to(OUTPUTS_DIR)
        key = str(rel).replace("\\", "/")
        if key not in mapping:
            mapping[key] = out_dir
    return mapping


def classify():
    videos = find_all_videos()
    outputs = find_output_dirs()

    matched: set[str] = set()
    queued: list[str] = []
    done: list[dict] = []
    failed: list[dict] = []

    for key, vpath in sorted(videos.items()):
        out = outputs.get(key)
        if out is None:
            queued.append(key)
        else:
            matched.add(key)
            report = out / "report.md"
            if report.exists():
                st = report.stat()
                done.append({
                    "name": key,
                    "size_kb": round(st.st_size / 1024),
                    "time": datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M"),
                    "timestamp": st.st_mtime,
                })
            else:
                failed.append({"name": key, "dir": str(out.relative_to(PROJECT_ROOT))})

    orphan = [k for k in outputs if k not in matched]

    return {
        "total": len(videos),
        "done": len(done),
        "queued": len(queued),
        "failed": len(failed),
        "orphan": len(orphan),
        "queued_list": queued,
        "failed_list": failed,
        "done_list": sorted(done, key=lambda x: x["timestamp"], reverse=True),
    }


# ── CLI output ──────────────────────────────────────────────────────

def print_cli(data: dict):
    lines = [
        f"[Videos] {data['total']} total  |  "
        f"[OK] {data['done']} done  |  "
        f"[QUEUE] {data['queued']} waiting  |  "
        f"[FAIL] {data['failed']} failed",
    ]
    if data["orphan"]:
        lines.append(f"[ORPHAN] {data['orphan']} output dirs without source")
    lines.append("")

    if data["queued_list"]:
        lines.append(f"--- Queued ({data['queued']}) ---")
        for name in data["queued_list"][:20]:
            lines.append(f"   {name}")
        if data["queued"] > 20:
            lines.append(f"   ... and {data['queued'] - 20} more")
        lines.append("")

    if data["failed_list"]:
        lines.append(f"--- Failed ({data['failed']}) ---")
        for f in data["failed_list"]:
            lines.append(f"   {f['name']}  ->  {f['dir']} (no report.md)")
        lines.append("")

    if data["done_list"]:
        lines.append(f"--- Recently Done (last 10) ---")
        for d in data["done_list"][:10]:
            lines.append(f"   {d['time']}  {d['name']}  ({d['size_kb']} KB)")

    print("\n".join(lines))


# ── HTTP server ─────────────────────────────────────────────────────

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Video-to-Text Pipeline</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;
  --ok:#3fb950;--queue:#d29922;--fail:#f85149;--accent:#58a6ff;}
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;background:var(--bg);
  color:var(--text);min-height:100vh;padding:24px}
h1{font-size:20px;font-weight:600;margin-bottom:20px}
.summary{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}
.stat{flex:1;min-width:140px;background:var(--card);border:1px solid var(--border);
  border-radius:8px;padding:16px;text-align:center}
.stat .num{font-size:36px;font-weight:700}
.stat .label{font-size:13px;color:var(--muted);margin-top:4px}
.stat.ok .num{color:var(--ok)}
.stat.queue .num{color:var(--queue)}
.stat.fail .num{color:var(--fail)}
.stat.total .num{color:var(--accent)}
.section{margin-bottom:20px}
.section h2{font-size:15px;font-weight:600;margin-bottom:8px;color:var(--muted)}
.list{background:var(--card);border:1px solid var(--border);border-radius:8px;
  overflow:hidden}
.item{display:flex;justify-content:space-between;align-items:center;padding:10px 16px;
  border-bottom:1px solid var(--border);gap:12px}
.item:last-child{border-bottom:none}
.item .path{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-family:SF Mono,Consolas,monospace;font-size:12px}
.item .meta{flex-shrink:0;font-size:12px;color:var(--muted)}
.status-bar{display:flex;align-items:center;gap:12px;margin-bottom:20px;font-size:12px;
  color:var(--muted)}
.status-bar .dot{width:8px;height:8px;border-radius:50%;background:var(--ok)}
.refresh{font-size:12px}
.empty{padding:24px;text-align:center;color:var(--muted)}
@media(max-width:600px){.summary{flex-direction:column}.stat{min-width:auto}}
</style>
</head>
<body>
<h1>&#127916; Video-to-Text Pipeline</h1>
<div class="status-bar">
  <div class="dot" id="dot"></div>
  <span id="updated">loading...</span>
  <span class="refresh">(auto-refresh 30s)</span>
</div>
<div class="summary">
  <div class="stat total"><div class="num" id="n-total">-</div><div class="label">Total</div></div>
  <div class="stat ok"><div class="num" id="n-done">-</div><div class="label">Done</div></div>
  <div class="stat queue"><div class="num" id="n-queue">-</div><div class="label">Queued</div></div>
  <div class="stat fail"><div class="num" id="n-fail">-</div><div class="label">Failed</div></div>
</div>
<div class="section" id="sec-queue" hidden>
  <h2>&#9200; Queued</h2><div class="list" id="list-queue"></div>
</div>
<div class="section" id="sec-fail" hidden>
  <h2>&#10060; Failed</h2><div class="list" id="list-fail"></div>
</div>
<div class="section">
  <h2>&#9989; Recently Done</h2><div class="list" id="list-done"></div>
</div>
<script>
async function load(){
  try{
    const r=await fetch('/api/status');
    const d=await r.json();
    document.getElementById('n-total').textContent=d.total;
    document.getElementById('n-done').textContent=d.done;
    document.getElementById('n-queue').textContent=d.queued;
    document.getElementById('n-fail').textContent=d.failed;
    document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString();
    document.getElementById('dot').style.background=d.queued>0?'var(--queue)':'var(--ok)';

    const qsec=document.getElementById('sec-queue');
    const qlist=document.getElementById('list-queue');
    if(d.queued_list.length){
      qsec.hidden=false;
      qlist.innerHTML=d.queued_list.map(n=>'<div class="item"><span class="path">'+esc(n)+
        '</span></div>').join('');
    }else{qsec.hidden=true}

    const fsec=document.getElementById('sec-fail');
    const flist=document.getElementById('list-fail');
    if(d.failed_list.length){
      fsec.hidden=false;
      flist.innerHTML=d.failed_list.map(f=>'<div class="item"><span class="path">'+esc(f.name)+
        '</span><span class="meta">no report.md</span></div>').join('');
    }else{fsec.hidden=true}

    const dlist=document.getElementById('list-done');
    if(d.done_list.length){
      dlist.innerHTML=d.done_list.map(x=>'<div class="item"><span class="path">'+esc(x.name)+
        '</span><span class="meta">'+x.time+'  '+x.size_kb+' KB</span></div>').join('');
    }else{dlist.innerHTML='<div class="empty">No reports yet.</div>'}
  }catch(e){console.error(e)}
}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
load();
setInterval(load,30000);
</script>
</body>
</html>"""


class StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}", flush=True)

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/status":
            self._json(classify())
        elif self.path == "/health":
            self._json({"status": "ok", "project": str(PROJECT_ROOT)})
        elif self.path == "/" or self.path == "/index.html":
            self._html(PAGE_HTML)
        else:
            self.send_response(404)
            self.end_headers()


def serve(port: int):
    server = HTTPServer(("0.0.0.0", port), StatusHandler)
    print(f"Dashboard: http://localhost:{port}")
    print(f"API:       http://localhost:{port}/api/status")
    print("Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Video-to-Text Pipeline Status")
    p.add_argument("--serve", "-s", action="store_true", help="Start web dashboard")
    p.add_argument("--port", "-p", type=int, default=8940, help="Port for --serve (default: 8940)")
    p.add_argument("--json", "-j", action="store_true", help="Output JSON instead of text")
    args = p.parse_args()

    if args.serve:
        serve(args.port)
    elif args.json:
        print(json.dumps(classify(), ensure_ascii=False, indent=2))
    else:
        print_cli(classify())


if __name__ == "__main__":
    main()
