$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path '.venv/Scripts/python.exe')) { throw '请先执行 README 中的依赖安装步骤。' }
if (-not (Test-Path 'frontend/dist/index.html')) { throw '请先在 frontend 目录执行 npm ci 和 npm run build。' }
Write-Host '光屿启动中：http://127.0.0.1:8000'
Write-Host '首次启动会在 data/local-access.json 生成控制凭证，用文本编辑器读取 control_token 并粘贴到页面。'
& ./.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 8192 --no-access-log
