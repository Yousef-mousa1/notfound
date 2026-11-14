# Dataset Facts

Status of each statement is labeled. **Everything in section 1 is `DATASET OBSERVATION`** from the uploaded sample files. Section 2 lists items that **must be verified** against official documentation before use.

> The current files are a **sample (Benin, 2012)**. More datasets will be added. Re-run the audit on each new dataset; do not assume these numbers hold elsewhere.

## 1. Observed in the sample files

Files: `modis_2012_Benin.csv` (≈1.39 MB), `viirs-snpp_2012_Benin.csv` (≈6.08 MB).

| | MODIS | VIIRS |
|---|---|---|
| Rows | 18,432 | 79,148 |
| `satellite` | Aqua 12,974 · Terra 5,458 | `N` only (79,148) |
| `instrument` | MODIS | VIIRS |
| `version` | 6.2 | 2 |
| Date range (`acq_date`) | 2012-01-01 → 2012-12-31 | 2012-01-20 → 2012-12-31 |
| Distinct dates | 194 | 263 |
| Missing values | 0 in all columns | 0 in all columns |
| Exact duplicate rows | 0 | 0 |
| Lat range | 6.2743 → 12.3644 | 6.25573 → 12.38073 |
| Lon range | 0.7711 → 3.8302 | 0.76289 → 3.83653 |
| `daynight` | D 18,094 · N 338 | D 73,112 · N 6,036 |
| `confidence` | integer 0–100 | string: `n` 57,641 · `l` 18,263 · `h` 3,244 |
| `type` | 0: 18,429 · 3: 3 | 0: 79,039 · 2: 103 · 3: 6 |
| `frp` (MW) median / mean / max | 16.0 / 29.65 / 1686.9 | 4.55 / 7.12 / 288.76 |
| `scan` range | 1.0 – 4.8 | 0.32 – 0.8 |
| `track` range | 1.0 – 2.0 | 0.36 – 0.78 |

### Columns

- **MODIS:** `latitude, longitude, brightness, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_t31, frp, daynight, type`
- **VIIRS:** `latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight, type`

### Specific observations

1. `acq_time` is an integer in HHMM form, so leading zeros are lost (e.g. `24` means 00:24). It must be zero-padded before parsing.
2. VIIRS contains rows with `bright_ti4 == 0` while `bright_ti5` is normal (example: 2012-02-12, ~11.306 N, 2.20 E, `confidence = l`). These look like invalid values rather than real temperatures. **Flag, do not delete.**
3. MODIS has very few distinct dates in June–September (Jun 5 · Jul 1 · Aug 2 · Sep 2), while VIIRS has more (Jun 17 · Jul 11 · Aug 10 · Sep 14). Because these files contain detections only, we **cannot** tell from them whether missing dates mean "no fire" or "no observation".
4. VIIRS starts on 2012-01-20, MODIS on 2012-01-01. The comparable overlap period must be defined explicitly.
5. The median FRP of MODIS is ≈3.5× that of VIIRS in this sample. `HYPOTHESIS` only: possibly related to pixel size and detection sensitivity. Must be tested, not assumed.
6. `type` takes values 0, 2, 3; value 2 appears only in VIIRS (103 rows).
7. Confidence scales are incompatible (numeric vs categorical).

## 2. TO VERIFY from official docs (do not assume)

- [ ] Exact product names / collection mapping for MODIS `version = 6.2` and VIIRS `version = 2` (FIRMS documentation).
- [ ] Official meaning of `type` values 0, 2, 3 and whether any should be filtered.
- [ ] Official MODIS confidence classes (commonly cited as low / nominal / high with numeric cut-offs) and VIIRS `l/n/h` meaning.
- [ ] Time zone of `acq_date` / `acq_time` (expected UTC; confirm).
- [ ] Meaning of `scan` / `track` (pixel footprint along/across scan; units) and how to use them for pixel area.
- [ ] Official meaning of `daynight`.
- [ ] Platform identification: `satellite` values (Terra, Aqua, `N`) and their overpass characteristics.
- [ ] Whether `bright_ti4 == 0` is documented as a fill/invalid value.
- [ ] Official recommendations on FRP comparison between MODIS and VIIRS and on combining the products.

For each item resolved, record the source URL and the date in `docs/decisions.md`.

## 3. Candidate unified schema (proposed, needs approval in Phase 01)

| Field | Meaning |
|---|---|
| `sensor_family` | MODIS / VIIRS |
| `platform` | Terra / Aqua / S-NPP (mapped from `satellite`) |
| `lat`, `lon` | WGS84 degrees |
| `datetime_utc` | parsed from `acq_date` + zero-padded `acq_time` |
| `frp_mw` | original FRP |
| `confidence_raw` | original value, unchanged |
| `confidence_class` | harmonized class (low / nominal / high), mapping stored in config |
| `daynight` | original |
| `type` | original |
| `scan`, `track` | original (footprint info) |
| `bright_primary`, `bright_secondary` | brightness / bright_t31 (MODIS), bright_ti4 / bright_ti5 (VIIRS) |
| `source_file`, `source_row` | traceability to the raw file |
| `qc_flags` | list of data-quality flags (e.g. `invalid_ti4`) |

Original columns are preserved; harmonized columns are **added**.

---
