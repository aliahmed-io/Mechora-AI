$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv-win\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create .venv-win and install backend/requirements-lock.txt first. See README.md.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'artifacts\model.joblib'))) { throw 'Train the model first: python -m backend.ml.train' }
$backendProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8001') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
try { Push-Location $projectRoot; npm run dev } finally { Pop-Location; if (-not $backendProcess.HasExited) { Stop-Process -Id $backendProcess.Id } }
