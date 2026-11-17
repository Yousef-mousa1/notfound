# DEPLOY.md — PyroScope (Frontend: Vercel · Backend: Cloud Run)

> **Status:** `PROPOSED METHOD` — هذا المستند مجرد deployment runbook، وليس ادّعاءً إن حاجة اتنشرت فعلاً.
> آخر تحديث: 2026-11-17

---

## 0. القرار وحدوده

| الجزء | المنصة | ليه |
|---|---|---|
| الفرونت (Vite/React) | **Vercel Hobby (مجاني)** | أنسب حاجة لـ SPA، وبيقرأ `VITE_API_BASE` من الـ env مباشرة (`frontend/src/api/client.js`). |
| الباك اند (Flask + DuckDB) | **Cloud Run (request-based, مجاني ضمن الحدود)** | يشغّل container حقيقي، عكس Firebase Hosting/Cloud Functions. |
| الحماية | **Basic Auth على nginx جوّه الـ container** | اختيارك. Cloud Run هيبقى `allow-unauthenticated` عشان الطلب يوصل لـ nginx اللي يسأل عن كلمة السر. |

**مصادر رسمية:**
- Cloud Run free tier (request-based، على أساس `us-central1`): **180,000 vCPU-second + 360,000 GiB-second + 2,000,000 request شهرياً**. https://cloud.google.com/run/pricing
- Cloud Storage FUSE volume mounts: **مش fully POSIX ومفيش file locking** → مش مناسب لـ DuckDB اللي محتاج random read/write على ملف واحد. https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts
- Firebase **مستبعد**: Flask + DuckDB + `JobRunner` thread + ملفات دائمة محتاجين long-running stateful host، مش Cloud Functions.

### حدود لازم تتقال في الـ demo
- **الديسك مؤقت.** نسخة `pyroscope.duckdb` (322 MB) بتتبعت جوّه الـ image. أي كتابة وقت التشغيل (import جديد، `qc_flags`، exports، jobs) بتضيع لما الـ instance يتوقف. ده تمام لـ demo قرائي، ومش تمام لـ system تسجّل بيانات.
- `JobRunner` background thread ممكن يتجمّد بين الطلبات لأن Cloud Run بيوقّف الـ CPU لما مفيش requests (default CPU throttling). استخدم الـ endpoints المتزامنة في العرض.
- الـ image حوالي **400 MB** (322 MB DB + 20 MB `dataSets` + ~38 MB modelling outputs)، فالـ cold start ممكن ياخد عشرات الثواني.
- Artifact Registry له free tier خاص بيه؛ راقب حجم الـ image لو زاد.
- Vercel Hobby مفيش password protection مدمج للـ frontend. الصفحة نفسها static ومفيهاش أسرار؛ الحماية على الـ API.

---

## 1. الملفات المطلوبة (لسه ما اتعملتش)

الخطوات دي بتفترض إنك **`cd /Users/yo/Documents/notfound`** (جذر الـ repo). أنشئ الملفات دول بنفس المحتوى:

### 1.1 `.dockerignore` (في جذر الـ repo، مش جوّه `deploy/`)

```dockerignore
.git/
frontend/
modeling/data/
modeling/src/
modeling/.venv/
backend/.venv/
backend/data/interim/
backend/data/processed/exports/
**/__pycache__/
*.pyc
*.pyo
```

> لاحظ: **مش** بنستبعد `backend/data/processed/pyroscope.duckdb` — دي النسخة اللي هتتبعت جوّه الـ image.

### 1.2 `deploy/Dockerfile`

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HARMONIZER_CONFIG=/app/backend/config/cloudrun.yaml

RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx apache2-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend /app/backend
COPY modeling/outputs /app/modeling/outputs

RUN python -m pip install --no-cache-dir -e /app/backend gunicorn \
 && mkdir -p /app/backend/data/processed/exports \
             /app/backend/data/interim/uploads \
             /var/log/nginx /run

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/start.sh /usr/local/bin/start.sh
RUN rm -f /etc/nginx/sites-enabled/default \
 && chmod +x /usr/local/bin/start.sh

EXPOSE 8080
CMD ["/usr/local/bin/start.sh"]
```

### 1.3 `deploy/nginx.conf`

```nginx
server {
    listen 8080;
    server_name _;

    client_max_body_size 64m;

    auth_basic "PyroScope demo";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_buffering off;
    }
}
```

### 1.4 `deploy/start.sh`

```sh
#!/bin/sh
set -eu

: "${PYROSCOPE_BASIC_USER:?PYROSCOPE_BASIC_USER is required}"
: "${PYROSCOPE_BASIC_PASSWORD:?PYROSCOPE_BASIC_PASSWORD is required}"

htpasswd -b -c /etc/nginx/.htpasswd \
  "$PYROSCOPE_BASIC_USER" "$PYROSCOPE_BASIC_PASSWORD"

cd /app/backend
gunicorn --bind 127.0.0.1:8000 \
         --workers 1 --threads 2 \
         --timeout 300 \
         wsgi:application &

exec nginx -g 'daemon off;'
```

### 1.5 `backend/wsgi.py`

```python
"""Gunicorn entrypoint for the deployed Flask application."""

import os

from app import create_app

application = create_app(os.environ.get("HARMONIZER_CONFIG"))
app = application
```

### 1.6 `backend/config/cloudrun.yaml`

انسخ الـ config الأصلي وعدّل سطرين بس:

```bash
cp backend/config/default.yaml backend/config/cloudrun.yaml
```

ثم في `backend/config/cloudrun.yaml`:

```yaml
api:
  prefix: "/api/v1"
  cors_origins:
    - "https://<your-project>.vercel.app"   # ← بدّله بدومين Vercel الفعلي
    - "http://localhost:5173"               # للاختبار المحلي فقط
  default_limit: 100
  max_limit: 1000
```

> **مهم:** `load_config()` **بي Load الملف كامل وما بيعملش merge** مع `default.yaml`، عشان كده لازم تنسخ الملف كامل وتعدّل جوه. المسارات النسبية زي `paths.estimates: "../modeling/outputs"` هتتحلّ تلقائياً لـ `/app/modeling/outputs` لأن `project_root()` = `/app/backend`.

### 1.7 `frontend/vercel.json`

```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }]
}
```

---

## 2. تجهيز Google Cloud (مرة واحدة)

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
export REPO="pyroscope"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION" \
  --description="PyroScope backend images"

gcloud auth configure-docker "$REGION-docker.pkg.dev"
```

أنشئ سر كلمة السر:

```bash
printf '%s' 'CHANGE_THIS_STRONG_PASSWORD' | \
  gcloud secrets create pyroscope-basic-password --data-file=-
```

---

## 3. بناء ورفع الـ image

```bash
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/pyroscope-api:latest"

docker build -f deploy/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
```

---

## 4. نشر الباك اند على Cloud Run

```bash
gcloud run deploy pyroscope-api \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --concurrency=1 \
  --cpu=1 \
  --memory=1Gi \
  --timeout=300 \
  --max-instances=2 \
  --set-env-vars=PYROSCOPE_BASIC_USER=demo \
  --set-secrets=PYROSCOPE_BASIC_PASSWORD=pyroscope-basic-password:latest
```

> `--allow-unauthenticated` **مش** معناها "مفيش حماية": معناها إن الطلب يوصل للـ container، ومن بعدين nginx يطلب Basic Auth. لو استخدمنا Cloud Run IAM بدل كده، الـ Basic Auth مش هيتشغّل خالص.

خد الـ URL:

```bash
gcloud run services describe pyroscope-api --region "$REGION" \
  --format='value(status.url)'
```

اختبره:

```bash
export API_URL="https://pyroscope-api-xxxxxxxx-xx.a.run.app"

curl -i "$API_URL/health"                                  # 401 Unauthorized
curl -u demo:CHANGE_THIS_STRONG_PASSWORD "$API_URL/health"  # 200 {"status":"ok",...}
curl -u demo:CHANGE_THIS_STRONG_PASSWORD \
  "$API_URL/api/v1/estimates/runs"
```

---

## 5. نشر الفرونت على Vercel

```bash
cd frontend
npx vercel link          # اربط المشروع أو أنشئه
npx vercel env add VITE_API_BASE production
# اكتب قيمة API_URL الناتجة من الخطوة 4 (من غير slash في الآخر)

npx vercel --prod
```

Vercel بيكتشف Vite تلقائياً: `Build Command = npm run build` و `Output Directory = dist`.

**بعد أول نشر:** خد دومين Vercel (`https://<project>.vercel.app`)، رجّع عدّل `backend/config/cloudrun.yaml`، وأعد بناء ورفع الـ image والـ deploy (الخطوتان 3 و4) عشان الـ CORS يبقى صح. لو الدومين اتغير لاحقاً، same dance.

تحقق من الفرونت: افتح الدومين → الصفحة لازم تحمّل، و `/harmonized` و `/analytics` يقرأوا من الـ API. لو ظهر CORS error، معنى إن `cors_origins` مبطّنش الدومين الصحيح.

---

## 6. بيانات لازم تكون موجودة جوّه الـ image

| المسار في الـ image | Source | الحجم |
|---|---|---|
| `/app/backend/data/processed/pyroscope.duckdb` | `backend/data/processed/pyroscope.duckdb` ( snapshot فيه 813,254 estimate + الـ observations) | 322 MB |
| `/app/backend/dataSets/` | CSVs بتاعة 2025 للخريطة والـ ingestion | 20 MB |
| `/app/modeling/outputs/harmonized.parquet` + `*.summary.json` | السلسلة الموحّدة | 12 MB |
| `/app/modeling/outputs/model_final/` | `model_meta.json` + `metrics.json` + SHA-256 pins | 6.2 MB |
| `/app/modeling/outputs/anomaly.parquet` | طبقة الشذوذ | 10 MB |

> **ما تنسخش** `backend/data/processed/exports/` (119 MB) — ملف `.dockerignore` في جذر الـ repo بيستبعدها. الـ exports بتتولد وقت التشغيل ومؤقتة على Cloud Run.

---

## 7. استكشاف الأخطاء

| العرض | السبب | الحل |
|---|---|---|
| `401` دايماً حتى مع `-u` | الـ بالدور قصاد nginx مش متولد | تأكد إن `PYROSCOPE_BASIC_USER/PASSWORD` موجودين في الـ service env/secret |
| CORS error في المتصفح | دومين Vercel مش في `api.cors_origins` | عدّل `cloudrun.yaml` وأعد الـ deploy |
| `FileNotFoundError: harmonized.parquet` | `modeling/outputs` مش متنسخة في الـ image | تأكد إن الـ docker build从其 الـ repo root (−f deploy/Dockerfile .) |
| الـ dashboard فاضي | الـ `model_runs` مش مستورد في الـ snapshot | أعد استيراد محلي قبل البناء: `python -m scripts.import_model_outputs --model-dir ../modeling/outputs/model_final --series ../modeling/outputs/harmonized.parquet --run-id est_pyro_2026_v1` |
| أول طلب بطيء جداً | cold start لصورة 400 MB | طبيعي؛ لو مهم، ارفع `--min-instances=1` (هيدخل في نطاق idle مدفوع) |
| `502 Bad Gateway` في أول ثانية بعد البدء | nginx بيبدأ قبل gunicorn يفتح المنفذ 8000 | استنى ثانية واعد الطلب؛ الـ 401 لازم يظهر أولاً، وبعدها 200. لو استمر، راجع `docker logs` |
| `artifact_path` في `/estimates/runs` فيه مسار macOS قديم | ده provenance من وقت الاستيراد الأصلي على جهاز التطوير، مش مسار جوّه الـ container | طبيعي؛ لا تحاول تفتحه على السيرفر. الملفات نفسها متنسوخة في `/app/modeling/outputs` |

---

## 7.1 تحقق محلي اتعمل بالفعل (2026-11-17)

- `docker build -f deploy/Dockerfile -t pyroscope-api:test .` → **نجح** (صورة ~400 MB).
- `docker run -p 18080:8080 -e PYROSCOPE_BASIC_USER=demo -e PYROSCOPE_BASIC_PASSWORD=...` →
  - بدون `-u`: `/health` رجّع **401**.
  - مع `-u`: `/health` رجّع **200** `{"status":"ok",...}`.
  - `/api/v1/estimates/runs` و`/api/v1/estimates/series` رجّعوا بيانات فعلية من الـ DuckDB المدمجة.
- `python -m json.tool frontend/vercel.json` → OK.
- **لسه متعملش:** الرفع الفعلي على Artifact Registry / Cloud Run / Vercel، وربط دومين Vercel الحقيقي في `cloudrun.yaml`.

## 8. Verify قبل الـ presentation

- [ ] `curl -u ... /health` → 200
- [ ] `curl -u ... /api/v1/estimates/runs` → فيه `est_pyro_2026_v1`
- [ ] `curl -u ... /api/v1/estimates/series?limit=5` → صفوف ليها `scale` و`is_estimate`
- [ ] Vercel: `/harmonized` و`/analytics` بيظهروا بيانات فعلية
- [ ] **بدون `-u`** أي endpoint يرجّع 401
- [ ] في العرض: قول إن `low/high` heuristic ±35%، وإن غياب الصف مش معناه مفيش حريق، وإن 2005/2006/2012 مش قابلين للتحقق المباشر

---

## 9. ليه مش Firebase / ليه مش VPS هنا

- Firebase Hosting = static بس، وCloud Functions = filesystem مؤقت + مفيش background thread دائم → محتاج إعادة معمارية كاملة (Firestore بدل DuckDB).
- VPS مجاني (Oracle Always Free) كان هيبقى أنسب لو الهدف **ديسك دائم + nginx حقيقي**، بس اختيارك كان Vercel + Cloud Run، فالمستند ده بيتبعه.
- لو احتجت state دائم لاحقاً: انقل الباك اند لـ VPS أو Render+Persistent Volume، وسيب Vercel زي ما هو.
