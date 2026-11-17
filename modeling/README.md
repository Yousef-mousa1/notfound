# modeling — توحيد MODIS و VIIRS

الهدف: تقويم واحد للحرائق النشطة يغطي سنين VIIRS (2013، 2024، 2025) والسنين
اللي عندنا فيها MODIS بس (2005، 2006، 2012) — من غير ما يبان فيه «هبوط» وهمي
بسبب تغيّر الحسّاس.

## الفكرة في سطرين

VIIRS بيشوف حرائق أكتر من MODIS بكتير. فالـ target هو **VIIRS**، والـ features
كلها من **MODIS** (وده الشيء الوحيد الموجود في 2005). الموديل بيتعلّم
`P(VIIRS > 0)` و`E[VIIRS]` من خلايا MODIS، وبعدين بنطبّق تصحيح تغطية `k`
عشان نرجّع الحرائق اللي VIIRS شافها في خلايا MODIS مش شايفها (VIIRS-only).

```
MODIS خام ──► cellday_YYYY.parquet ──► train.py ──► model_*.joblib
                                              │
                          predict.py ◄────────┘
                               │
                     backcast (سنين VIIRS مش موجودة)
                               │
observed VIIRS ────────────────┴──► harmonize.py ──► anomaly.py
```

## خطوات التشغيل بالترتيب

### 1) بناء جداول الخلية-اليوم (0.05°)

```bash
.venv/bin/python src/build_cellday.py \
    --modis data/raw/modis_2013 --viirs data/raw/viirs_2013 \
    --out data/processed/cellday_2013.parquet
# نفس الشيء لـ 2024 و 2025
```

بيكتب جنب كل ملف:
- `cellday_YYYY.parquet` — صف لكل (خلية، يوم) فيها MODIS، مع أهداف VIIRS.
- `cellday_YYYY.coverage.parquet` — جدول `k` لكل (بلوك 1°، شهر): كل VIIRS ÷
  VIIRS اللي جوّه الجدول.
- `cellday_YYYY.summary.json` — تقرير التنظيف والتغطية.

**حماية من الـfalse zeros**: كل ملف MODIS بيتقصّ على المدى الزمني الفعلي لملف
VIIRS بتاع نفس البلد. لو VIIRS ناقص شهر، MODIS بتاع الشهر ده بيتشال بدل ما
يتسجّل «صفر حرائق».

### 2) التدريب بتقسيم بالسنين (الأهم)

```bash
.venv/bin/python src/train.py \
    --data data/processed/cellday_2013.parquet data/processed/cellday_2025.parquet \
    --out outputs/run_year2024 --split year --test-year 2024
```

- `--split year` هو التقييم الصح: المنتج بيتنبأ بسنة **مشافهاش**، فالتقييم لازم
  يكون كده. (`--split time/space` موجودين للمقارنة بس.)
- الموديل بيتدرب على 2013+2025، ويتظبط على جزء منهم، ويتقاس على 2024.
- الـcount موديل **غير شرطي** (Poisson على كل الصفوف، بما فيها الأصفار)، فـ
  `predict.py` مش بيصفّر التوقعات.
- الاحتمالات بتتعاير بـ isotonic على الـvalidation، وبيتسجّل Brier.
- فيه تقرير شهري (region×month) لأن ده اللي التقويم بيعرضه فعلاً.

#### إيه معنى "التقييم" هنا (مهم)

- **2013 و 2024:** فيه `year holdout` حقيقي مقابل **VIIRS مرصود** — يعني
  validation مقابل reference مرصود ومحجوز، مش مجرد consistency بين حسّاسين.
  (الـ2013 extrapolation والـ2024 year-holdout، وكلهم مقابل VIIRS مش MODIS.)
- **2025:** VIIRS مرصود وموجود في السلسلة، بس السنة ساهمت في التدريب/الضبط،
  فمش holdout مستقل.
- **2005 / 2006 / 2012:** VIIRS أصلاً ما كانش موجود قبل 20 يناير 2012، فمفيش
  reference مباشرة نتحقق بيها من الـbackcast — ده **مش قابل للتحقق مباشرة بالتصميم**،
  مش "دقة عالية".
- لذلك أي رقم تقييم هنا معناه "مدى قرب التوقع من VIIRS المرصود في السنين المحجوزة"،
  **مش** إثبات إن الحريق حصل فعلاً، ولا إثبات إن الـbackcast صحيح في السنين القديمة.

### 3) الـbackcast للسنين اللي فيها MODIS بس

```bash
.venv/bin/python src/predict.py --modis data/raw/modis_2005 \
    --model outputs/run_year2024 --out outputs/backcast/viirs_like_2005.parquet
# 2006 و 2012 نفس الشيء
```

كل صف بيتعلّم `is_estimate = true`. المخرج **شرطي** (خلايا MODIS بس)، وبيتحوّل
للمقياس الكامل في الخطوة الجاية بـ`k`.

### 4) السلسلة الموحّدة

```bash
.venv/bin/python src/harmonize.py \
    --observed data/processed/cellday_2013.parquet \
               data/processed/cellday_2024.parquet \
               data/processed/cellday_2025.parquet \
    --backcast outputs/backcast/viirs_like_2005.parquet \
               outputs/backcast/viirs_like_2006.parquet \
               outputs/backcast/viirs_like_2012.parquet \
    --coverage data/processed/cellday_2013.coverage.parquet \
               data/processed/cellday_2024.coverage.parquet \
               data/processed/cellday_2025.coverage.parquet \
    --out outputs/harmonized.parquet
```

بيطلع مقياسين جنب بعض:

| المقياس | إيه هو | متى تستخدمه |
|---|---|---|
| `viirs_harmonized` | VIIRS المرصود أو الـbackcast، مضروب في `k` | السلسلة الأساسية للتقويم |
| `modis_raw` | عدّ MODIS زي ما هو | مقارنة أطول، من غير أي موديل |

ملاحظات مهمة:
- **VIIRS المرصود نفسه بيتضرب في `k`** — لأنه في الجدول ده شرطي على MODIS
  برضه. من غير كده سنة 2013 هتبان أقل من 2005 بـ4 أضعاف، وده أثر الحسّاس مش
  أثر الحرائق.
- `low`/`high` باند **تقريبي** (±35%) على الصفوف المصحّحة، مش فترة ثقة محسوبة.
- لو سنة موجودة في الاتنين، المرصود بيكسب والـbackcast بيتشال مع تحذير.

### 5) طبقة الشذوذ (بدون ML)

```bash
.venv/bin/python src/anomaly.py --series outputs/harmonized.parquet \
    --out outputs/anomaly.parquet
```

- Leave-one-year-out لكل (منطقة × شهر من السنة): median / MAD / p10 / p90 من
  **السنين التانية**.
- لكل صف: `percentile`، `robust_z = (x - median) / (1.4826·MAD)`، و`severity`
  من `very_low` لـ`very_high`.
- الترتيب الاحتياطي: `region_month` → `global_month` → `global`، والعمود
  `baseline_level` بيقولك أي مستوى اتستخدم.
- `baseline_n` = عدد السنين اللي اتبنى عليها الأساس. **مهم**: عندنا 3 سنين
  VIIRS، فالـMAD خشن؛ متصدّقش تصنيف شدة من غير ما تبص على `baseline_n`.
- الأداء الافتراضي: الأساس من السنين **المرصودة** بس، عشان تقدير الموديل ما
  يحرّكش الأساس اللي بيتقاس عليه. `--include-estimates` بيضمّهم.

## الأرقام الحالية

| السنة | النوع | صفوف الجدول | VIIRS جوّه الجدول |
|---|---|---|---|
| 2013 | مرصود | 2,346,284 | 41.4% |
| 2024 | مرصود | 2,554,319 | 43.5% |
| 2025 | مرصود | 2,055,230 | 37.1% |
| 2005 / 2006 / 2012 | backcast | — | — |

`k` العالمي ≈ 2.45 (معامل واحد لكل بلوك/شهر، مش ثابت).

## نتائج التقييم (year holdout)

| الاختبار | Presence (calibrated) | Count | Monthly |
|---|---|---|---|
| test = 2024 | ROC 0.711 / PR 0.744 / Brier 0.217 (baseline PR 0.656) | MAE 2.812 / R² 0.515 | sum ratio 1.067 / Spearman 0.937 |
| test = 2013 (extrapolation) | ROC 0.711 / PR 0.799 / Brier 0.226 (baseline PR 0.722) | MAE 2.432 / R² 0.503 | sum ratio 0.977 / Spearman 0.993 |

الاختبار التاني هو الأقرب لحالة الـ backcast (تدريب على 2024+2025 واختبار على
سنة أقدم). النتيجتين بتأكدوا إن المجموع الشهري متحكم فيه، بس لسه مفيش دليل على
دقة 2005 نفسها (مفيش VIIRS هناك نتحقق منه).

**معايرة الـ backcast:** متوسط `k` لكل (منطقة × شهر) محسوب على توزيع مكاني
خاص بالسنين المرصودة. لما نتطبّقه على توزيع 2005/2006/2012 المختلف، المجموع
بيطلع أعلى ~30% من المتوسط المرصود. عشان كده `harmonize.py` بيعمل raking
لـ `k` بحيث المتوسط المرجّح يساوي `global_k` مع الحفاظ على الشكل النسبي لكل
منطقة/شهر (العمود `baseline` بيبقى `region_month_raked`). الـ flag
`--no-rake-k` يوقف ده عشان نقارن. دي **خطوة معايرة إحصائية مش اكتشاف علمي**.

## القيود اللي لازم تتقال

1. **3 سنين مرصودة بس** — كفاية لسلسلة، مش كفاية لثقة عالية في الشذوذ.
2. **الموديل بيشوف خلايا MODIS بس** — `k` بيعالج ده إحصائيًا، مش بيخلق تفاصيل
   مكانية.
3. **`k` سنوي/شهري مش عشوائي**: بيصحّح فرق الحسّاس، بس لو VIIRS نفسه اتغيّر
   (تغيّر خوارزمية، منصّة جديدة) التصحيح مش هيشوف ده.
4. **2005/2006/2012 تقديرات** — كل صف فيهم معلّم `is_estimate = true`، ولازم
   تتلوّن/تتعلّم في الواجهة كده.
5. **LightGBM/XGBoost** محتاجين `libomp` على macOS. لو مش موجود، `train.py`
   بيكمّل بـ`HistGradientBoosting` من sklearn (نفس العيلة، نتايج قريبة).

## تسليم النتيجة للباك اند (Option B)

الموديل هو **المصدر الوحيد** للسلسلة الموحّدة. الباك اند ما بيحسبهاش تاني،
وما بيكتبهاش في `observations` أبدًا.

```bash
cd ../backend
PYTHONPATH=src:. .venv/bin/python -m scripts.import_model_outputs \
  --model-dir ../modeling/outputs/model_final \
  --series ../modeling/outputs/harmonized.parquet \
  --manifest ../modeling/outputs/backend_import.manifest.json
```

اللي بيحصل:

1. `POST /api/v1/estimates/runs` — تسجيل `run_id` مع ميتاداتا الموديل ومقاييس
   الـheld-out (من `metrics.json`). مقاييس التقييم مش من الـrefit.
2. `POST /api/v1/estimates/import` — قراءة الـparquet بـ`read_parquet` في
   DuckDB وتخزينه في جدول `estimates` بـ`INSERT OR IGNORE` (الاستيراد
   idempotent ومفيش overwrite).
3. `GET /api/v1/dashboard/estimates-calendar` — سلسلة شهرية فيها
   `observed_value` و`estimated_value` في عمودين منفصلين.

الجداول الجديدة: `model_runs` (provenance) و`estimates` (الصفوف).
`observations` ما اتمسّش. الـ`low/high` **heuristic band مش CI**، ولازم
يتقال في الواجهة. الـ`region` في السلسلة هو بلوك شبكة (مش دولة)، عشان كده
اللوحة المنفصلة هي المناسب دلوقتي، مش كالندر الدولة الحالي.

الواجهة: صفحة `/harmonized` في الفرونت بتقرأ الـ endpoint ده، وتفصل بين
السنين المرصودة والـ backcast (دائرة زرقاء)، وتعرض الـ heuristic band، وتسيب
كالندر detections الحالي من غير تغيير.
