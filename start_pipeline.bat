@echo off
REM Auto-start Video-to-Text pipeline server
REM Waits for Tailscale to be ready, then binds to Tailscale IP

cd /d "E:\Desktop\Video_to_Text"

echo [%date% %time%] Waiting for Tailscale...
:check_ts
"C:\Program Files\Tailscale\tailscale.exe" status >nul 2>&1
if errorlevel 1 (
    timeout /t 5 /nobreak >nul
    goto check_ts
)

echo [%date% %time%] Tailscale ready. Starting pipeline server...
"C:\anaconda3\envs\Video_to_Text\python.exe" pipeline_server.py --port 8940
