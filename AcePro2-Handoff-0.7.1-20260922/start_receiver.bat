@echo off
cd /d "%~dp0"
py -3 android/desktop/receiver.py --port 8765 --output runtime/received_batches
pause
