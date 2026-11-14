# PyroScope — تشغيل المشروع على Windows (backend + frontend)
# الاستخدام: كليك يمين على الملف -> Run with PowerShell
# أو من PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\run_windows.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Set-Location $backend

Write-Host "[1/5] تجهيز الـ Python venv ..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

Write-Host "[2/5] تثبيت مكتبات الـ backend ..." -ForegroundColor Cyan
pip install -q -e .

Write-Host "[3/5] بناء قاعدة البيانات (أول مرة بس) ..." -ForegroundColor Cyan
if (-not (Test-Path "data\processed\pyroscope.duckdb")) {
    python -m scripts.demo_run
}

Write-Host "[4/5] تشغيل الـ backend على http://127.0.0.1:5000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$backend'; . .\.venv\Scripts\Activate.ps1; python -m flask --app app run --port 5000"
)

Start-Sleep -Seconds 3
Write-Host "[5/5] تجهيز الـ frontend ..." -ForegroundColor Cyan
Set-Location $frontend
if (-not (Test-Path "node_modules")) {
    npm install
}
Write-Host "افتح http://localhost:5173 بعد ما يبدأ Vite" -ForegroundColor Green
npm run dev