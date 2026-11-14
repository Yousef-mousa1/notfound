"""Analytics request models."""

from __future__ import annotations

from .observations import ObservationQuery


class AnalyticsQuery(ObservationQuery):
    """Observation filters plus an optional harmonization run."""

    run_id: str | None = None
