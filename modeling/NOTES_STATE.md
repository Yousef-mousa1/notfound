# حالة الشغل — 2026-11-14

## الداتا الجديدة (من المستخدم)
- `/home/ubuntu/upload/MODISDataset.csv` → نُسخ إلى `/home/ubuntu/modeling/data/raw/global2025/MODIS_2025_global.csv` (131,653 صف، 2025-01-01 → 2025-12-01، عالمي)
- `/home/ubuntu/upload/VIIRSDataset.csv` → `/home/ubuntu/modeling/data/raw/global2025/VIIRS_SNPP_2025_global.csv` (129,762 صف، نفس الفترة، عالمي)
- **مشكلة**: الملفان **عيّنة عشوائية رقيقة** من الداتا العالمية (~393 detection/يوم لكل حساس بدل آلاف)، ومش مأخوذين من نفس الشرائح المكانية/الزمنية، فالـ overlap على 0.05° = 4.1% فقط.
- **VIIRS file headers** = أسماء أعمدة MODIS (`brightness`, `bright_t31`) بدل `bright_ti4/bright_ti5`؛ `instrument=SNPP`. اتظبط في `src/build_cellday.py` عبر `column_mapping()`.

## اللي اتعمل على الداتا الجديدة
- `data/processed/cellday_2025_global.parquet` (0.05°): 119,846 MODIS cell-day، positive rate 4.07% (overlap ضعيف جدًا → غير صالح للتدريب).
- `data/processed/cellday_2025_global_1deg.parquet` (1.0°): 74,443 cell-day، positive rate 36.25%.
- التدريب: `outputs/run_global2025_1deg/` — best cls = hist_gradient_boosting__none (ROC 0.786، PR 0.672، F1 0.642)، best reg = xgboost__none (MAE 0.632، R² 0.350، Spearman 0.505)، FRP R² 0.007.
- grid option اتضاف: `build_cellday.py --grid 1.0` و`train.py --grid 1.0`.

## المطلوب من المستخدم
عيّنات **متطابقة** (نفس bbox + نفس التواريخ، بدون تنقيص عشوائي):
```
python tools\sample_firms.py --input "modis.csv" --out dataSets --bbox W,S,E,N --start 2025-01-01 --end 2025-03-31
python tools\sample_firms.py --input "viirs.csv" --out dataSets --bbox W,S,E,N --start 2025-01-01 --end 2025-03-31
```

## أدوات اتضافت للباكدج
- `tools/sample_firms.py` (فلترة bbox + تاريخ، streaming)
- `tools/split_firms_csv.py` (تقسيم ملفات كبيرة لأجزاء 400k صف)
- الباكدج: `/home/ubuntu/pyroscope_full_project.zip` (يحتاج إعادة بناء بعد آخر تعديلات tools)
