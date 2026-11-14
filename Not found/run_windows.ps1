# PyroScope — تشغيل المشروع على Windows (backend + frontend)
# الاستخدام: كليك يمين على الملف -> Run with PowerShell
# أو من PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\run_windows.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "[1/4] تجهيز الـ Python venv ..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

Write-Host "[2/4] تثبيت مكتبات الـ backend ..." -ForegroundColor Cyan
pip install -q -e .

Write-Host "[3/4] تشغيل الـ backend على http://127.0.0.1:5000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$root'; . .\.venv\Scripts\Activate.ps1; python -m flask --app app run --port 5000"
)

Start-Sleep -Seconds 3
Write-Host "[4/4] تجهيز الـ frontend ..." -ForegroundColor Cyan
Set-Location (Join-Path $root "notfound-main")
if (-not (Test-Path "node_modules")) {
    npm install
}
Write-Host "افتح http://localhost:5173 بعد ما يبدأ Vite" -ForegroundColor Green
npm run dev
