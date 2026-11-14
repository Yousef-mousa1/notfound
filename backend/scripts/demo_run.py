"""End-to-end demo runner (Phase 09).

Rebuilds the whole demonstrable state on a database in one command:

    ingest -> grid -> harmonize (ratio) -> validate -> detect anomalies -> export

Every step goes through the same HTTP endpoints the API exposes, so the script
cannot take a shortcut the API does not allow. Nothing is deleted or
overwritten: imports are idempotent by SHA-256, grids can be reused, and every
run/export is a new, identifiable record. The script writes one manifest JSON
with the ids it created and the limitations that apply.

Usage (from the project root):

    python -m scripts.demo_run
    python -m scripts.demo_run --grid-km 25 --radius-m 1500 --time-window-h 2
    python -m scripts.demo_run --file dataSets/modis_2012_Benin.csv --new-grid
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from app import create_app
from harmonizer.config import load_config, resolve_path
from harmonizer.export import software_versions
from harmonizer.io.loaders import detect_file_sensor
from harmonizer.store.jobs import utcnow

IMPORT_STATUS_OK = {200, 201}

LIMITATIONS = [
    "The source files contain detections only: absence of a row is not absence of fire.",
    "MODIS (~1 km) and VIIRS (375 m) detections are not interchangeable and are never merged.",
    "FRP is instantaneous power (MW); no energy is derived.",
    "Validation metrics are cross-sensor consistency, not accuracy.",
    "Anomalies are statistical outliers in daily per-cell counts, not confirmed fire events.",
]


class DemoError(RuntimeError):
    """A demo step failed; the message carries the API error code."""


def _call(
    client,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call one API endpoint and return its ``data`` payload."""
    response = client.open(path, method=method, json=body) if body is not None else client.open(
        path, method=method
    )
    payload = response.get_json(silent=True) or {}
    if response.status_code not in IMPORT_STATUS_OK:
        error = payload.get("error") or {}
        raise DemoError(
            f"{method} {path} failed ({response.status_code}): "
            f"{error.get('code', 'error')} - {error.get('message', 'no message')}"
        )
    return payload.get("data", payload)


def _scan_raw_files(config: dict[str, Any]) -> list[Path]:
    """Every CSV in the raw directory whose header identifies a supported sensor."""
    raw_dir = resolve_path(config, "paths", "raw")
    files: list[Path] = []
    for path in sorted(raw_dir.glob("*.csv")):
        try:
            if detect_file_sensor(path):
                files.append(path)
        except Exception:  # noqa: BLE001 - a non-detection CSV is simply skipped
            continue
    return files


def _import_files(client, paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Import each file through the ingestion endpoint (idempotent)."""
    results: list[dict[str, Any]] = []
    for path in paths:
        sensor = detect_file_sensor(path)
        if sensor is None:
            raise DemoError(f"Cannot detect a sensor from the header of {path}.")
        data = _call(
            client,
            "POST",
            f"/api/v1/ingestion/sources/import/{sensor}",
            {"path": str(path)},
        )
        already = bool(data.get("already_imported"))
        previous = data.get("import") or {}
        results.append(
            {
                "sensor": sensor,
                "file": str(path),
                "status": "already imported" if already else "imported",
                "rows_loaded": previous.get("rows_loaded") if already else data.get("rows_loaded"),
                "duplicates_skipped": previous.get("duplicates") if already else data.get("duplicate_rows"),
            }
        )
    return results


def _pick_or_create_grid(
    client, cell_km: float, reuse: bool
) -> tuple[str, bool]:
    """Reuse the newest grid with the same cell size, or create a new one."""
    if reuse:
        listing = _call(client, "GET", "/api/v1/processing/grid?limit=1000")
        for grid in listing:
            if abs(float(grid.get("cell_km") or 0) - cell_km) < 1e-9:
                return str(grid["grid_id"]), True

    created = _call(
        client,
        "POST",
        "/api/v1/processing/grid/generate",
        {"cell_km": cell_km, "name": f"demo-{cell_km:g}km"},
    )
    return str(created["grid_id"]), False


def run_demo(
    config_path: str | Path | None = None,
    *,
    grid_km: float = 25.0,
    radius_m: float = 1500.0,
    time_window_h: float = 2.0,
    files: Iterable[str | Path] | None = None,
    reuse_grid: bool = True,
    create_exports: bool = True,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full demo pipeline and return the manifest."""
    config = load_config(config_path)
    app = create_app(config_path)
    app.config["TESTING"] = True
    client = app.test_client()

    manifest: dict[str, Any] = {
        "generated_at": utcnow().isoformat() + "Z",
        "config_path": str(config_path) if config_path else "config/default.yaml",
        "parameters": {
            "grid_km": grid_km,
            "radius_m": radius_m,
            "time_window_h": time_window_h,
            "reuse_grid": reuse_grid,
        },
        "steps": [],
        "ids": {},
        "limitations": LIMITATIONS,
        "software": software_versions(),
    }

    try:
        raw_files = [Path(item) for item in files] if files else _scan_raw_files(config)
        if not raw_files:
            raise DemoError(
                "No detection CSV found. Pass --file or put files in the raw directory."
            )

        imports = _import_files(client, raw_files)
        manifest["steps"].append({"step": "ingest", "files": imports})

        statistics = _call(client, "GET", "/api/v1/observations/statistics")
        detections = int(statistics["overall"]["detections"])
        if detections == 0:
            raise DemoError("No observations stored after ingestion; cannot continue.")
        manifest["steps"].append(
            {
                "step": "observations",
                "detections": detections,
                "per_sensor": {
                    row["sensor"]: row["detections"] for row in statistics["per_sensor"]
                },
            }
        )

        grid_id, reused = _pick_or_create_grid(client, grid_km, reuse_grid)
        manifest["ids"]["grid_id"] = grid_id
        manifest["steps"].append({"step": "grid", "grid_id": grid_id, "reused": reused})

        harmonized = _call(
            client,
            "POST",
            "/api/v1/harmonization/run",
            {
                "grid_id": grid_id,
                "time_bucket": "day",
                "method": "ratio",
                "radius_m": radius_m,
                "time_window_h": time_window_h,
            },
        )
        manifest["ids"]["harmonization_run_id"] = harmonized["run_id"]
        manifest["steps"].append(
            {
                "step": "harmonize",
                "run_id": harmonized["run_id"],
                "n_pairs": harmonized.get("n_pairs"),
                "n_cells": harmonized.get("n_cells"),
            }
        )

        validation = _call(
            client,
            "POST",
            "/api/v1/validation/run",
            {"radius_m": radius_m, "time_window_h": time_window_h},
        )
        manifest["ids"]["validation_run_id"] = validation["run_id"]
        manifest["steps"].append(
            {
                "step": "validate",
                "run_id": validation["run_id"],
                "n_pairs": validation.get("n_pairs"),
            }
        )

        anomalies = _call(
            client, "POST", "/api/v1/anomalies/detect", {"grid_id": grid_id}
        )
        anomaly_stats = anomalies.get("stats") or {}
        manifest["ids"]["anomaly_run_id"] = anomalies["run_id"]
        manifest["steps"].append(
            {
                "step": "anomalies",
                "run_id": anomalies["run_id"],
                "series_total": anomaly_stats.get("series_total"),
                "n_anomalies": anomaly_stats.get("anomalies"),
            }
        )

        if create_exports:
            exports = []
            exports.append(
                (
                    "observations",
                    _call(client, "POST", "/api/v1/exports/observations", {}),
                )
            )
            exports.append(
                (
                    "harmonized-data",
                    _call(
                        client,
                        "POST",
                        "/api/v1/exports/harmonized-data",
                        {"run_id": harmonized["run_id"]},
                    ),
                )
            )
            exports.append(
                (
                    "validation-report",
                    _call(
                        client,
                        "POST",
                        "/api/v1/exports/validation-report",
                        {"run_id": validation["run_id"]},
                    ),
                )
            )
            manifest["ids"]["export_ids"] = [record["export_id"] for _, record in exports]
            manifest["steps"].append(
                {
                    "step": "export",
                    "exports": [
                        {
                            "kind": kind,
                            "export_id": record["export_id"],
                            "row_count": record.get("row_count"),
                            "files": [
                                {"name": item["name"], "sha256": item["sha256"]}
                                for item in record.get("files", [])
                            ],
                        }
                        for kind, record in exports
                    ],
                }
            )

        target = (
            Path(manifest_path)
            if manifest_path is not None
            else resolve_path(config, "paths", "processed") / "demo_manifest.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
        )
        manifest["manifest_path"] = str(target)
        return manifest
    finally:
        app.extensions["job_runner"].stop()
        app.extensions["db"].close()


def _print_summary(manifest: dict[str, Any]) -> None:
    steps = {item["step"]: item for item in manifest["steps"]}
    print("PyroScope demo run")
    print(f"  generated : {manifest['generated_at']}")
    print(f"  manifest  : {manifest.get('manifest_path')}")
    ingest = steps.get("ingest", {}).get("files", [])
    for item in ingest:
        print(
            f"  ingest    : {str(item.get('sensor')):<5} {str(item.get('status')):<16} "
            f"rows_loaded={item.get('rows_loaded')}"
        )
    observations = steps.get("observations", {})
    print(
        f"  observed  : {observations.get('detections', 0):,} detections "
        f"{observations.get('per_sensor', {})}"
    )
    grid = steps.get("grid", {})
    print(f"  grid      : {grid.get('grid_id')} (reused={grid.get('reused')})")
    harmonize = steps.get("harmonize", {})
    print(
        f"  harmonize : {harmonize.get('run_id')} "
        f"pairs={harmonize.get('n_pairs')} cells={harmonize.get('n_cells')}"
    )
    validate = steps.get("validate", {})
    print(f"  validate  : {validate.get('run_id')} pairs={validate.get('n_pairs')}")
    anomaly = steps.get("anomalies", {})
    print(
        f"  anomalies : {anomaly.get('run_id')} "
        f"series={anomaly.get('series_total')} flagged={anomaly.get('n_anomalies')}"
    )
    for export in steps.get("export", {}).get("exports", []):
        print(
            f"  export    : {str(export.get('kind')):<17} {export.get('export_id')} "
            f"rows={export.get('row_count')}"
        )
    print("  open      : http://127.0.0.1:5000/demo")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="Config YAML (default: config/default.yaml).")
    parser.add_argument("--grid-km", type=float, default=25.0, help="Grid cell size in km.")
    parser.add_argument("--radius-m", type=float, default=1500.0, help="Matching radius in m.")
    parser.add_argument("--time-window-h", type=float, default=2.0, help="Matching window in h.")
    parser.add_argument(
        "--file",
        action="append",
        default=None,
        help="Detection CSV to import (repeatable). Defaults to scanning the raw directory.",
    )
    parser.add_argument("--new-grid", action="store_true", help="Create a new grid instead of reusing one.")
    parser.add_argument("--no-exports", action="store_true", help="Skip the export step.")
    parser.add_argument("--manifest", default=None, help="Where to write the manifest JSON.")
    args = parser.parse_args(argv)

    try:
        manifest = run_demo(
            args.config,
            grid_km=args.grid_km,
            radius_m=args.radius_m,
            time_window_h=args.time_window_h,
            files=args.file,
            reuse_grid=not args.new_grid,
            create_exports=not args.no_exports,
            manifest_path=args.manifest,
        )
    except DemoError as error:
        print(f"demo failed: {error}", file=sys.stderr)
        return 1
    _print_summary(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
