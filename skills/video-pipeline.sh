#!/bin/bash
# Video Pipeline Wrapper for Nova (Linux)
# Called by Nova's video-to-text skill on mote-home
set -euo pipefail

PROJECT_ROOT="/mnt/data/Video_to_Text"
CONDA_ENV="Video_to_Text"
CONDA_BIN="$HOME/miniconda3/bin/conda"

# Helper: run a Python script in the conda env
run_python() {
    "$CONDA_BIN" run -n "$CONDA_ENV" python "$@"
}

action="${1:-}"
target="${2:-}"

case "$action" in
    list)
        echo "=== 可用视频 ==="
        find "$PROJECT_ROOT/videos" -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.webm" -o -iname "*.avi" -o -iname "*.mov" -o -iname "*.flv" \) \
            ! -name ".*" \
            -printf "%T@ %s %p\n" 2>/dev/null | sort -rn | while read -r ts size path; do
            rel="${path#$PROJECT_ROOT/}"
            size_mb=$(echo "scale=0; $size / 1048576" | bc)
            echo "  $rel  (${size_mb}MB)"
        done
        ;;

    process-dir)
        if [ -z "$target" ]; then
            echo "ERROR: 请指定目录名或日期，如 videos/2026-07-26"
            exit 1
        fi
        dir_path="$target"
        if [ ! -d "$dir_path" ]; then
            dir_path="$PROJECT_ROOT/$target"
        fi
        if [ ! -d "$dir_path" ]; then
            dir_path="$PROJECT_ROOT/videos/$target"
        fi
        if [ ! -d "$dir_path" ]; then
            echo "ERROR: 目录不存在: $target"
            exit 1
        fi
        echo "=== 批量处理: $dir_path ==="
        shopt -s nocaseglob
        videos=("$dir_path"/*.{mp4,mkv,webm,avi,mov,flv})
        shopt -u nocaseglob
        if [ ${#videos[@]} -eq 0 ]; then
            echo "目录中没有视频文件"
            exit 0
        fi
        for v in "${videos[@]}"; do
            [ -f "$v" ] || continue
            echo "--- 处理: $(basename "$v") ---"
            run_python "$PROJECT_ROOT/main.py" "$v"
        done
        echo "=== 全部完成 ==="
        ;;

    process)
        if [ -z "$target" ]; then
            echo "ERROR: 请指定视频路径"
            exit 1
        fi
        vid_path="$target"
        # If not absolute, make relative to project root
        if [[ "$vid_path" != /* ]]; then
            vid_path="$PROJECT_ROOT/$target"
        fi
        if [ ! -f "$vid_path" ]; then
            echo "ERROR: 视频不存在: $vid_path"
            exit 1
        fi
        echo "=== 处理: $vid_path ==="
        run_python "$PROJECT_ROOT/main.py" "$vid_path"
        echo "=== 完成 ==="
        ;;

    status)
        run_python "$PROJECT_ROOT/status.py"
        ;;

    recent)
        run_python "$PROJECT_ROOT/status.py"
        ;;

    dashboard)
        echo "Starting dashboard at http://100.118.10.0:8940 ..."
        run_python "$PROJECT_ROOT/status.py" --serve --port 8940
        ;;

    *)
        echo "Usage: $0 {list|process-dir|process|status|recent|dashboard} [target]"
        echo ""
        echo "Actions:"
        echo "  list              List all available videos"
        echo "  process-dir DIR   Process all videos in a directory"
        echo "  process VIDEO     Process a single video"
        echo "  status            Show pipeline status"
        echo "  recent            Show recently processed videos"
        echo "  dashboard         Start web dashboard on port 8940"
        exit 1
        ;;
esac
