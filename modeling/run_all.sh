#!/usr/bin/env bash
# End-to-end run: observed years -> model -> backcast -> harmonized series -> anomalies.
#
#   ./run_all.sh              # full pipeline
#   ./run_all.sh --skip-build # reuse existing cellday_*.parquet
#
# Everything lands in data/processed/ and outputs/. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
OBSERVED_YEARS=(2013 2024 2025)
BACKCAST_YEARS=(2005 2006 2012)
TEST_YEAR=2024
EVAL_RUN="outputs/run_year${TEST_YEAR}"       # metrics + transition figure
FINAL_MODEL="outputs/model_final"             # shipped artifact (all years)
BACKCAST_DIR="outputs/backcast"

if [[ "${1:-}" != "--skip-build" ]]; then
  for year in "${OBSERVED_YEARS[@]}"; do
    echo "== cellday $year =="
    "$PY" src/build_cellday.py \
      --modis "data/raw/modis_${year}" \
      --viirs "data/raw/viirs_${year}" \
      --out "data/processed/cellday_${year}.parquet" \
      --summary "data/processed/cellday_${year}.summary.json"
  done
fi

DATA=(data/processed/cellday_2013.parquet data/processed/cellday_2024.parquet data/processed/cellday_2025.parquet)

echo "== evaluate on held-out ${TEST_YEAR} =="
"$PY" src/train.py --data "${DATA[@]}" --out "$EVAL_RUN" --split year --test-year "$TEST_YEAR"

echo "== shipped model (retrained on every year) =="
"$PY" src/train.py --data "${DATA[@]}" --out "$FINAL_MODEL" \
  --split year --test-year "$TEST_YEAR" --refit-all

mkdir -p "$BACKCAST_DIR"
for year in "${BACKCAST_YEARS[@]}"; do
  echo "== backcast $year =="
  "$PY" src/predict.py \
    --modis "data/raw/modis_${year}" \
    --model "$FINAL_MODEL" \
    --out "${BACKCAST_DIR}/viirs_like_${year}.parquet"
done

echo "== harmonize =="
"$PY" src/harmonize.py \
  --observed "${DATA[@]}" \
  --backcast "${BACKCAST_DIR}"/viirs_like_2005.parquet \
             "${BACKCAST_DIR}"/viirs_like_2006.parquet \
             "${BACKCAST_DIR}"/viirs_like_2012.parquet \
  --coverage data/processed/cellday_2013.coverage.parquet \
             data/processed/cellday_2024.coverage.parquet \
             data/processed/cellday_2025.coverage.parquet \
  --out outputs/harmonized.parquet --csv

echo "== anomaly =="
"$PY" src/anomaly.py --series outputs/harmonized.parquet --out outputs/anomaly.parquet --csv

echo "== figures =="
"$PY" src/make_figures.py --run "$EVAL_RUN" --series outputs/harmonized.parquet

echo
echo "done. see outputs/harmonized.summary.json, outputs/anomaly.summary.json, outputs/figures/"
