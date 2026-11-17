# حالة الشغل — 2026-11-17

> طريقة التشغيل الكاملة والمنهجية في `modeling/README.md`.
> الملف ده سجل حالة بس.

## المسارات (النسخة الحالية)
- المشروع: `/Users/yo/Documents/notfound/modeling`
- Python: `.venv/bin/python` (3.13.11) — مفيش `python` على الـPATH
- الداتا الخام: `data/raw/{modis,viirs}_YYYY/...` (ملفات بلد-بلد)
- المعالَج: `data/processed/cellday_YYYY.parquet` + `.coverage.parquet` + `.summary.json`
- المخرجات: `outputs/harmonized.parquet`، `outputs/anomaly.parquet`، `outputs/figures/`
- الباك اند: `../backend` — جداول `model_runs` + `estimates`، صفحة `/harmonized`

## اللي خلص
- `build_cellday.py`: نافذة VIIRS لكل بلد، جدول `k` لكل (بلوك 1°، شهر)، تقرير تغطية.
- `train.py`: `--split year`, isotonic calibration + Brier, تقرير شهري region×month,
  bootstrap CI، قرار FRP على الـvalidation، `--refit-all`.
- `predict.py`: مفيش تصفير للـcounts غير الشرطية، بيعاير الاحتمال، بيكتب
  `viirs_like_frp_expected`.
- `harmonize.py`: مقياسين، تصحيح `k` للمرصود والـbackcast، **raking** لـ `k`
  على المتوسط العالمي، مخرج طويل + عريض + `--csv`.
- `anomaly.py`: LOO لكل (region×month_of_year), median/MAD/p10/p90، percentile,
  robust_z، severity، ترتيب احتياطي 3 مستويات، `--include-estimates`.
- `make_figures.py`: شكل الانتقال + شكل الكالندر.
- `run_all.sh`: كل الخطوات في أمر واحد.
- تقييم 2024 و 2013 (year holdout) + refit نهائي + 3 backcasts + سلسلة + شواذ.
- **Option B** في الباك اند: جداول + 6 endpoints + `/dashboard/estimates-calendar`
  + `scripts/import_model_outputs.py` + 4 اختبارات (المجموع 135/135 نجحوا).
- فرونت: صفحة `/harmonized` منفصلة عن كالندر detections. build + lint نجحوا.

## أرقام نهائية
- التقييم 2024: PR 0.744 / Brier 0.217 / count MAE 2.812 / monthly ratio 1.067.
- التقييم 2013 (extrapolation): PR 0.799 / count MAE 2.432 / monthly ratio 0.977.
- rake factor = 0.790. بعده نسبة VIIRS/MODIS: 4.42–4.54 (backcast) مقابل 4.14–4.71 (مرصود).
- الاستيراد: `est_pyro_2026_v1` — 813,254 صف، 2005-01 → 2025-12.

## تنظيف (2026-11-17)
اتشالت: تجربة Nov-14 القديمة (`run_global2025_1deg`, تقريرها)، ملفات smoke
المؤقتة، نسخ الـCSV المكررة، `outputs/backcast/`, و`frontend/dist`.
الـ backcasts تتولد تاني بـ`run_all.sh`. المخرجات النهائية والـDuckDB سليمة.

## اللي باقي / تحذيرات
- التقييم مقابل VIIRS مرصود ومحجوز موجود لـ2013 و2024 بس (year holdout)؛ 2025 ساهمت في التدريب فمش holdout مستقل.
- مفيش VIIRS أصلاً قبل 20 يناير 2012، فـbackcasts 2005/2006/2012 مش قابلة للتحقق المباشر بالتصميم — مش "دقة عالية".
- `baseline_n` صغير (2–3 سنين) في طبقة الشواذ — الشدة خشنة.
- `low/high` heuristic ±35% مش CI.
- تجميع حسب الدولة (country-level) مش متاح في السلسلة — الـregion بلوك شبكة.
- LightGBM/XGBoost محتاجين `libomp` (brew timeout). sklearn بيكمّل.
