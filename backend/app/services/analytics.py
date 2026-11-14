"""Analytics service: sensor-separated trends and cross-sensor summaries.

FRP endpoints report instantaneous power (MW) only. Nothing is converted to
energy, and MODIS/VIIRS counts are never merged into a single "hotspot" count.
"""

from __future__ import annotations

from typing import Any

from harmonizer.store import Database
from harmonizer.store import sql

from ..errors import ApiError
from ..schemas.analytics import AnalyticsQuery
from . import anomalies as anomaly_service
from . import harmonization as harmonization_service
from . import observations, validation

TREND_NOTES = [
    "Sensors are reported separately and never summed into one hotspot count.",
    "FRP is instantaneous radiative power (MW); no energy is derived.",
    "The sample is a single year, so no multi-year trend is claimed.",
    "Detection counts depend on observation coverage; a gap is not proof of no fire.",
]


def overview(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Dataset-wide summary with availability of downstream runs."""
    stats = observations.statistics(database, query)
    filters = query.as_filters()
    extent_sql, extent_params = sql.extent(filters)
    extent = database.fetch_one(extent_sql, extent_params) or {}

    anomaly_run = anomaly_service.latest_run(database)
    harmonization_run = harmonization_service.latest_successful(database)
    validation_run = validation.latest(database)

    return {
        "observations": stats["overall"],
        "per_sensor": stats["per_sensor"],
        "platforms": observations.by_sensor(database, query),
        "extent": extent,
        "available_outputs": {
            "anomaly_run_id": anomaly_run["run_id"] if anomaly_run else None,
            "harmonization_run_id": (
                harmonization_run["run_id"] if harmonization_run else None
            ),
            "validation_run_id": validation_run["run_id"] if validation_run else None,
            "land_cover": "not implemented: no land-cover dataset is registered",
        },
        "notes": [
            "MODIS (~1 km) and VIIRS (375 m) detections are not interchangeable.",
            "Absence of a row is not absence of fire; sources contain detections only.",
            TREND_NOTES[1],
        ],
    }


def hotspot_trends(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Detection counts per sensor per time bucket."""
    rows = observations.by_date(database, query)
    return {
        "granularity": query.granularity,
        "series": rows,
        "notes": TREND_NOTES,
    }


def frp_trends(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """FRP statistics per sensor per time bucket."""
    rows = observations.by_date(database, query)
    return {
        "granularity": query.granularity,
        "series": rows,
        "statistics": ["mean_frp_mw", "median_frp_mw", "max_frp_mw", "min_frp_mw"],
        "notes": [
            "FRP is instantaneous radiative power (MW); it is never summed into energy.",
            "Mean FRP per bucket is a summary of detected pixel power, not total energy.",
            *TREND_NOTES[:1],
            TREND_NOTES[2],
        ],
    }


def activity_trends(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Harmonized activity index per time bucket from a stored run."""
    if query.run_id:
        run_row = harmonization_service.get_run(database, query.run_id)
        if run_row is None:
            raise ApiError(
                "harmonization_run_not_found",
                f"No harmonization run with id '{query.run_id}'.",
                404,
            )
        if run_row.get("status") != "succeeded":
            raise ApiError(
                "no_results",
                f"Harmonization run '{query.run_id}' has status '{run_row.get('status')}'.",
                409,
            )
    else:
        run_row = harmonization_service.latest_successful(database)
        if run_row is None:
            raise ApiError(
                "no_harmonization_run",
                "No successful harmonization run exists; call POST /harmonization/run first.",
                409,
            )

    trend_sql, trend_params = sql.activity_trend(run_row["run_id"])
    rows = database.fetch_all(trend_sql, trend_params)
    time_bucket = (run_row.get("params") or {}).get("time_bucket")
    return {
        "run_id": run_row["run_id"],
        "method": run_row["method"],
        "time_bucket": time_bucket,
        "series": rows,
        "notes": [
            "The harmonized activity index is unitless and relative to the run's own p95 scales.",
            "A single bucket labelled 'all' means the run was aggregated without a time bucket.",
            "Check sensors_present when interpreting the index.",
        ],
    }


def daily(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Daily detection and FRP series per sensor."""
    scoped = query.model_copy(update={"granularity": "day"})
    return hotspot_trends(database, scoped)


def monthly(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Monthly detection and FRP series per sensor."""
    scoped = query.model_copy(update={"granularity": "month"})
    return hotspot_trends(database, scoped)


def yearly(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Yearly series with an explicit no-trend-claim flag."""
    scoped = query.model_copy(update={"granularity": "year"})
    payload = hotspot_trends(database, scoped)
    return {
        **payload,
        "trend_claim": False,
        "notes": [
            "The sample covers a single year; this is not a multi-year trend.",
            *TREND_NOTES,
        ],
    }


def regions(database: Database, query: AnalyticsQuery, region_grid: int) -> list[dict[str, Any]]:
    """Counts per data-extent region (not administrative boundaries)."""
    return observations.regions(database, query, region_grid)


def sensor_comparison(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Side-by-side sensor statistics plus the latest consistency snapshot."""
    stats = observations.statistics(database, query)
    validation_run = validation.latest(database)

    agreement: dict[str, Any] | None = None
    if validation_run:
        metrics = validation_run.get("metrics") or {}
        agreement = {
            "run_id": validation_run["run_id"],
            "n_pairs": metrics.get("n_pairs"),
            "log10_frp": metrics.get("log10_frp"),
            "raw_mw": metrics.get("raw_mw"),
            "limitations": metrics.get("limitations"),
        }

    return {
        "sensors": stats["per_sensor"],
        "platforms": observations.by_sensor(database, query),
        "agreement": agreement,
        "notes": [
            "Counts and FRP statistics are reported per sensor; they are never merged.",
            "Agreement metrics come from matched pairs and are cross-sensor consistency, not accuracy.",
            "MODIS (~1 km) and VIIRS (375 m) detect different numbers of pixels for the same fire.",
        ],
    }
