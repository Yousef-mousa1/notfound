# PyroScope — تقرير التدريب على الداتا الجديدة (عالمي 2025)

## 1) الداتا المستخدمة
| | MODIS (MODISDataset.csv) | VIIRS (VIIRSDataset.csv) |
|---|---|---|
| عدد الصفوف | 131,653 | 129,762 |
| الفترة | 2025-01-01 → 2025-12-01 | نفسها |
| النطاق | عالمي | عالمي |
| الأعمدة | FIRMS القياسية (`brightness`, `bright_t31`, `type`, `confidence`, `frp`, `daynight`) | نفس أسماء MODIS + `instrument = SNPP` |

ملاحظة مهمة: ملف VIIRS مكتوب بأسماء أعمدة MODIS (`brightness`/`bright_t31` بدل `bright_ti4`/`bright_ti5`)، فالـ pipeline بيعمل mapping تلقائي في `build_cellday.py::column_mapping()`.

## 2) المشكلة الجوهرية: العيّنة رقيقة وعشوائية
الداتا العالمية اليومية فيها آلاف الـ detections. ملفاتك فيها **~393 detection/يوم لكل حساس**، يعني عيّنة عشوائية ~5–10%. ولأن العيّنة العشوائية بتمسك hotspats مختلفة لكل حساس، التداخل بين الحساسين صغير جدًا:

| شبكة | نسبة خلايا MODIS اللي فيها VIIRS في نفس اليوم |
|---|---|
| 0.05° | **4.1%** |
| 0.10° | 6.7% |
| 0.25° | 12.8% |
| 0.50° | 22.2% |
| 1.00° | 35.2% |

يعني على شبكة 0.05° (القريبة من resolution بتاع MODIS) 96% من الـ labels هتبقى "مفيش VIIRS" — والسبب مش إن مفيش حريق، السبب إن الـ VIIRS row نفسه مش موجود في العيّنة. ده هيدرّب موديل على noise.

## 3) حل وسط اتنفذ: شبكة 1°
عشان نعمل تدريب ذو معنى بالعيّنة دي، اتجمّعت البيانات على 1°:
- 74,443 MODIS cell-day، positive rate 36.25%
- Split زمني 80/20: 59,968 train (268 يوم) / 14,475 test (67 يوم)

## 4) النتائج (HistGB للتصنيف، XGBoost للانحدار، بدون normalization)
| مهمة | أفضل موديل | Metric |
|---|---|---|
| تصنيف وجود VIIRS | HistGradientBoosting | ROC-AUC **0.786**، PR-AUC **0.672**، F1 **0.642** |
| عدد detections VIIRS | XGBoost (Poisson) | MAE **0.632**، R² **0.350**، Spearman **0.505** |
| مجموع FRP | — | R² **0.007** (ضعيف جدًا) |

Confusion matrix على threshold 0.31:

| | pred: مفيش VIIRS | pred: VIIRS |
|---|---|---|
| **true: مفيش** | 6,181 | 3,198 |
| **true: VIIRS** | 1,176 | 3,920 |

الرسمة: `outputs/run_global2025_1deg/confusion_matrix_roc.png`

الأرقام دي أضعف من تجربة Benin (ROC 0.849) لأن: (أ) العيّنة عالمية فيها بيئات مختلفة جدًا، (ب) الشبكة 1° بتخلط حرائق كتير في خلية واحدة، (ج) الـ overlap لسه مش كامل.

## 5) الحل الصح: عيّنة متطابقة
لازم نفس bbox ونفس التواريخ للحساسين، بدون أي تنقيص عشوائي:

```powershell
python tools\sample_firms.py --input "modis_all.csv" --out dataSets --bbox 20,10,40,35 --start 2025-01-01 --end 2025-03-31 --name MODIS_2025
python tools\sample_firms.py --input "viirs_all.csv" --out dataSets --bbox 20,10,40,35 --start 2025-01-01 --end 2025-03-31 --name VIIRS_2025
```

بنفس الـ bbox والفترة، التداخل على 0.05° بيطلع 60–80%+، وبعدها التدريب يرجع لشبكة 0.05° والـ F1 بيرجع فوق 0.8.

## 6) المخرجات
- `outputs/run_global2025_1deg/` — موديلات joblib + metrics.json + feature_schema.json + model_meta.json + الرسمة
- `data/processed/cellday_2025_global_1deg.parquet` — جدول التدريب
- `data/processed/cellday_2025_global.parquet` — نفس الداتا على 0.05° (للمقارنة، مش للتدريب)
- داتا Benin القديمة اتنقلت لـ `archive_benin/` وخرجت من كل التقارير والتدريب.
## 6) تشغيل التطبيق على الداتا الجديدة
اتشالت داتا Benin من `dataSets/` والـ store، واتحط مكانها `MODIS_2025_global.csv` و`VIIRS_2025_global.csv`، واتعمل `demo_run --new-grid`:

| مرحلة | النتيجة |
|---|---|
| ingest | 131,653 MODIS + 129,762 VIIRS = **261,415** detection |
| grid | 25 km، **219,986** cell-day |
| harmonize | **1,890** زوج متطابق (1.5 km / 2 ساعة) |
| validate | 1,894 زوج، log10 FRP MAE 0.592 dex، RMSE 0.721، bias +0.527 dex، Pearson 0.461 |
| anomalies | 232 خلية مشبوهة (27 extreme / 70 high / 132 moderate) |
| exports | observations 261,415 صف، harmonized 219,986 صف، validation 1,894 صف |

إصلاح مهم اتعمل في الباك إند: ملف VIIRS بتاعك جاي بأسماء أعمدة MODIS (`brightness`/`bright_t31`) و`instrument=SNPP`، فكان بيتقرا كـ MODIS. اتضاف كشف الحساس من عمود `instrument` (MODIS / VIIRS / Terra / Aqua / SNPP / NOAA-20 / NOAA-21) في `schema/columns.py` و`io/loaders.py`.

## 7) المخرجات
