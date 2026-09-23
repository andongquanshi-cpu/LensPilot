$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Missing .venv. See README.' }
if (-not (Test-Path 'frontend/dist/index.html')) { throw 'Missing frontend/dist. Run npm run build in frontend.' }
Write-Host 'http://127.0.0.1:8000'
& ./.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 8192 --no-access-log
