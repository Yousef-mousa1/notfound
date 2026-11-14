# PyroScope

NASA Space Apps Cairo 2026 · Challenge #8 · Team **Not Found**

توحيد بيانات MODIS و VIIRS للحرائق النشطة وعرضها في تقويم وتحليلات.

## الهيكل

- `backend/` — Flask + DuckDB (التحليل والـ API)
- `frontend/` — React + Vite (الواجهة)
- `modeling/` — تدريب الموديل (التفاصيل في `modeling/NOTES_STATE.md`)

## 1) الباك

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m scripts.demo_run
python -m flask --app app run --port 5000
```

Windows (PowerShell):

```powershell
cd backend
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m scripts.demo_run
python -m flask --app app run --port 5000
```

`demo_run` بيبني قاعدة DuckDB من الملفات الموجودة في `backend/dataSets/`، وبتعمله مرة واحدة (القاعدة نفسها مش في الريبو). بعدها تقدر تشغّل السيرفر بس.

للاختبارات: `python -m pytest` (من جوه `backend/` والـ venv شغال).

## 2) الفرونت (في terminal تاني)

```bash
cd frontend
npm install
npm run dev
```

وافتح `http://localhost:5173`. الـ Vite proxy بيودّي `/api` للباك على بورت 5000.

## تحقق سريع

- `http://127.0.0.1:5000/health` لازم يرد `ok`
- `http://127.0.0.1:5000/api/v1/dashboard/overview` لازم يرجّع أرقام بعد `demo_run`

## مشاكل شائعة

| المشكلة | الحل |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process Bypass` |
| `Port 5000 is in use` | شغّل على بورت تاني (`--port 5001`) وحدّث `server.proxy` في `frontend/vite.config.js` |
| الواجهة فاضية أو "API unreachable" | الباك مش شغال، أو `demo_run` ما اتعملش |
| `Could not set lock on file ...duckdb` | فيه سيرفر تاني شغال على نفس القاعدة، اقفله الأول |