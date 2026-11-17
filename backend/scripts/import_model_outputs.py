"""Import the modeling layer's final series into the API store.

This is the hand-off step after ``modeling/run_all.sh``. It registers the model
run (provenance + held-out metrics) and imports the harmonized parquet through
the same HTTP endpoints the API exposes, so it cannot bypass validation.

Usage (from the backend directory)::

    python -m scripts.import_model_outputs \\
        --model-dir ../modeling/outputs/model_final \\
        --series ../modeling/outputs/harmonized.parquet

Nothing is written to ``observations`` and no raw file is modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import create_app

IMPORT_STATUS_OK = {200, 201}


class ImportError_(Exception):
    """A structured failure from one of the calls."""


def _call(client, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.open(path, method=method, json=body)
    payload = response.get_json(silent=True) or {}
    if response.status_code not in IMPORT_STATUS_OK:
        error = payload.get("error") or {}
        raise ImportError_(
            f"{method} {path} failed ({response.status_code}): "
            f"{error.get('code', 'error')} - {error.get('message', 'no message')}"
        )
    return payload.get("data", payload)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ImportError_(f"Required modeling artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    test = metrics.get("test") or {}
    return {
        "split": metrics.get("split"),
        "classification_validation": metrics.get("classification_calibrated_validation"),
        "regression_validation": metrics.get("regression"),
        "test_presence_calibrated": test.get("presence_calibrated"),
        "test_count": test.get("count"),
        "test_monthly_count": test.get("monthly_count"),
        "frp_useful": metrics.get("frp_useful"),
    }


def _resolve(path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else (Path.cwd() / candidate).resolve()


def run_import(
    config_path: str | Path | None = None,
    *,
    model_dir: str | Path,
    series: str | Path,
    run_id: str | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Register the run and import its series; return a manifest."""
    model_path = _resolve(str(model_dir))
    series_path = _resolve(str(series))
    if not series_path.is_file():
        raise ImportError_(f"Harmonized series not found: {series_path}")

    meta = _read_json(model_path / "model_meta.json")
    metrics = _read_json(model_path / "metrics.json")
    summary_path = series_path.with_suffix(".summary.json")
    series_summary = _read_json(summary_path) if summary_path.is_file() else {}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    resolved_run_id = run_id or f"est_{stamp}"

    app = create_app(config_path)
    app.config["TESTING"] = True
    client = app.test_client()
    manifest: dict[str, Any] = {
        "generated_at": stamp,
        "run_id": resolved_run_id,
        "model_dir": str(model_path),
        "series": str(series_path),
        "source_summary": series_summary,
        "notes": (
            "Model-produced estimates only. observations is never modified. "
            "low/high are a heuristic band, not a fitted confidence interval."
        ),
    }
    try:
        manifest["model_run"] = _call(
            client,
            "POST",
            "/api/v1/estimates/runs",
            {
                "run_id": resolved_run_id,
                "model_name": str(meta.get("presence_model", "unknown")),
                "method": (
                    f"presence={meta.get('presence_model')}; count={meta.get('count_model')}; "
                    f"calibration={meta.get('calibration')}; "
                    f"refit_on_all_rows={meta.get('refit_on_all_rows')}"
                ),
                "trained_years": series_summary.get("observed_years"),
                "test_year": meta.get("test_year"),
                "validation_split": meta.get("validation_split"),
                "metrics": _compact_metrics(metrics),
                "artifact_path": str(model_path),
                "notes": "Held-out metrics come from the evaluation run; shipped model was refit on all rows.",
            },
        )
        manifest["import"] = _call(
            client,
            "POST",
            "/api/v1/estimates/import",
            {"run_id": resolved_run_id, "path": str(series_path), "level": "region"},
        )
        manifest["run_detail"] = _call(
            client, "GET", f"/api/v1/estimates/runs/{resolved_run_id}"
        )
    finally:
        app.extensions["db"].close()

    if manifest_path is not None:
        output = _resolve(str(manifest_path))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        manifest["manifest_path"] = str(output)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="Config YAML (default: config/default.yaml).")
    parser.add_argument("--model-dir", required=True, help="Directory with model_meta.json and metrics.json.")
    parser.add_argument("--series", required=True, help="outputs/harmonized.parquet from harmonize.py.")
    parser.add_argument("--run-id", default=None, help="Stable run id (default: generated UTC stamp).")
    parser.add_argument("--manifest", default=None, help="Where to write the manifest JSON.")
    args = parser.parse_args(argv)

    try:
        manifest = run_import(
            args.config,
            model_dir=args.model_dir,
            series=args.series,
            run_id=args.run_id,
            manifest_path=args.manifest,
        )
    except (ImportError_, FileNotFoundError, json.JSONDecodeError) as error:
        print(f"import failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({
        "run_id": manifest["run_id"],
        "rows_added": manifest["import"]["rows_added"],
        "rows_read": manifest["import"]["rows_read"],
        "period_min": manifest["import"]["period_min"],
        "period_max": manifest["import"]["period_max"],
        "manifest": manifest.get("manifest_path"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
