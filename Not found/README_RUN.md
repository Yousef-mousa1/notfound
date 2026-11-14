# تشغيل PyroScope على Windows

## خطأ `npm error enoent` — السبب

الخطأ معناها إن npm مش لاقي `package.json` في المجلد اللي بتشغل فيه. الـ `notfound-main` عندك
فيه `src` و`public` و`vite.config.js` بس، ومفيش `package.json` ولا `package-lock.json`، فالـ npm
بيوقف قبل ما يبدأ. ده لأن الـ zip اللي فككته قبل كده كان فيه **الملفات المعدّلة بس** مش المشروع كامل.

الحل: استخدم الباكدج الكامل `pyroscope_full_project.zip` — فيه `package.json` و`package-lock.json`
والـ backend كله والـ DuckDB store الجاهز (32 MB) بالداتا.

## خطوات التشغيل (PowerShell)

```powershell
# 1) فك الضغط
Expand-Archive -Path "$HOME\Downloads\pyroscope_full_project.zip" -DestinationPath "C:\" -Force

# 2) الأسهل: السكربت الجاهز
cd "C:\Not found"
Set-ExecutionPolicy -Scope Process Bypass
.\run_windows.ps1
```

السكربت بيعمل: venv → `pip install -e .` → يشغّل الـ backend في نافذة لوحدها على `127.0.0.1:5000`
→ `npm install` لو لسه → `npm run dev` على `http://localhost:5173`.

### لو عايز تعملها يدوي

```powershell
cd "C:\Not found"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

# نافذة أولى: الـ backend
python -m flask --app app run --port 5000

# نافذة تانية: الـ frontend
cd "C:\Not found\notfound-main"
npm install
npm run dev
```

## تحقق سريع

- `http://127.0.0.1:5000/health` → `{"service":"harmonizer-api","status":"ok",...}`
- `http://127.0.0.1:5000/api/v1/dashboard/overview` → JSON فيه 97,580 detection
- `http://localhost:5173` → الواجهة، والـ Vite proxy بيودّي `/api` للـ backend تلقائيًا
- اختبارات الـ backend: `python -m pytest` (كلها لازم تنجح)

## مشاكل شائعة

| المشكلة | الحل |
|---|---|
| `npm error enoent` | `package.json` ناقص — استخدم الباكدج الكامل |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process Bypass` |
| `Port 5000 is in use` | غيّر المنفذ: `python -m flask --app app run --port 5001` وحدّث `server.proxy` في `notfound-main/vite.config.js` |
| الواجهة فاضية / "API unreachable" | الـ backend مش شغال، أو المنفذ مختلف |
| `python` مش موجود | نزّل Python 3.12 من python.org وعلّم "Add to PATH" |
