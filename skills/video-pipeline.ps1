# Video Pipeline Wrapper for Nova
# Called by Nova's video-to-text skill
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("list", "process-dir", "process", "status", "recent", "dashboard")]
    [string]$Action,

    [string]$Target = ""
)

$ProjectRoot = "e:\Desktop\Video_to_Text"
$CondaEnv = "Video_to_Text"

# Helper: run a command in conda env and return output
function Invoke-CondaPython {
    param([string]$Args)
    $cmd = "conda activate $CondaEnv; python $Args"
    $result = & powershell -NoProfile -Command "conda activate $CondaEnv; python $Args" 2>&1
    return $result -join "`n"
}

switch ($Action) {
    "list" {
        # List all video files
        Write-Output "=== 可用视频 ==="
        Get-ChildItem -Path "$ProjectRoot\videos" -Recurse -Include *.mp4, *.mkv, *.webm, *.avi, *.mov, *.flv |
            Where-Object { $_.Name -notmatch '^\.' } |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object {
                $relPath = $_.FullName.Replace($ProjectRoot, "").TrimStart("\")
                $sizeGB = [math]::Round($_.Length / 1GB, 2)
                $date = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm")
                Write-Output "  $relPath  (${sizeGB}GB, $date)"
            }
    }

    "process-dir" {
        # Process all videos in a directory
        if (-not $Target) {
            Write-Output "ERROR: 请指定目录名或日期，如 videos/2026-07-26"
            exit 1
        }
        $dirPath = "$ProjectRoot\$Target"
        if (-not (Test-Path $dirPath)) {
            # Try videos/ prefix
            $dirPath = "$ProjectRoot\videos\$Target"
        }
        if (-not (Test-Path $dirPath)) {
            Write-Output "ERROR: 目录不存在: $Target"
            exit 1
        }
        Write-Output "=== 批量处理: $dirPath ==="
        $videos = Get-ChildItem -Path $dirPath -Include *.mp4, *.mkv, *.webm, *.avi, *.mov, *.flv |
            Where-Object { $_.Name -notmatch '^\.' }
        if (-not $videos) {
            Write-Output "目录中没有视频文件"
            exit 0
        }
        foreach ($v in $videos) {
            Write-Output "--- 处理: $($v.Name) ---"
            Invoke-CondaPython -Args "main.py `"$($v.FullName)`""
        }
        Write-Output "=== 全部完成 ==="
    }

    "process" {
        # Process single video
        if (-not $Target) {
            Write-Output "ERROR: 请指定视频路径"
            exit 1
        }
        $vidPath = $Target
        if (-not [System.IO.Path]::IsPathRooted($Target)) {
            $vidPath = "$ProjectRoot\$Target"
        }
        if (-not (Test-Path $vidPath)) {
            Write-Output "ERROR: 视频不存在: $vidPath"
            exit 1
        }
        Write-Output "=== 处理: $vidPath ==="
        Invoke-CondaPython -Args "main.py `"$vidPath`""
        Write-Output "=== 完成 ==="
    }

    "status" {
        Invoke-CondaPython -Args "status.py"
    }

    "recent" {
        Invoke-CondaPython -Args "status.py"
    }

    "dashboard" {
        Write-Output "Starting dashboard at http://localhost:8940 ..."
        Invoke-CondaPython -Args "status.py --serve --port 8940"
    }
}
