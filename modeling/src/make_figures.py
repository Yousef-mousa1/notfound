"""Figures for the write-up / pitch.

Two independent figures:

1. ``--run outputs/run_year2024`` — how the held-out year looks: predicted vs
   observed monthly totals, and a region x month scatter with the 1:1 line.
2. ``--series outputs/harmonized.parquet`` — the full calendar: global monthly
   totals for every year, observed years solid, backcast years dashed.

Usage:
    python src/make_figures.py --run outputs/run_year2024 --outdir outputs/figures
    python src/make_figures.py --series outputs/harmonized.parquet --outdir outputs/figures
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

OBSERVED = "#1f77b4"
ESTIMATE = "#d62728"


def transition_figure(run: Path, outdir: Path) -> Path:
    monthly = pd.read_csv(run / "test_monthly.csv")
    monthly["month"] = pd.to_datetime(monthly["month"])
    by_month = monthly.groupby("month")[["truth", "prediction"]].sum().sort_index()

    figure, (left, right) = plt.subplots(1, 2, figsize=(13, 5))

    left.plot(by_month.index, by_month["truth"], marker="o", color=OBSERVED, label="observed VIIRS")
    left.plot(by_month.index, by_month["prediction"], marker="s", ls="--", color=ESTIMATE, label="predicted")
    left.set_title("Held-out year: monthly VIIRS hotspots")
    left.set_ylabel("detections")
    left.tick_params(axis="x", rotation=45)
    left.legend()
    left.grid(alpha=0.3)
    ratio = by_month["prediction"].sum() / max(by_month["truth"].sum(), 1e-9)
    left.text(
        0.02,
        0.95,
        f"total ratio = {ratio:.2f}\nmonths = {len(by_month)}",
        transform=left.transAxes,
        va="top",
        fontsize=9,
    )

    right.scatter(monthly["truth"], monthly["prediction"], s=10, alpha=0.35, color=OBSERVED)
    limit = max(monthly["truth"].max(), monthly["prediction"].max())
    right.plot([0, limit], [0, limit], color="black", lw=1, label="1:1")
    right.set_xlabel("observed (region x month)")
    right.set_ylabel("predicted (region x month)")
    right.set_title("Region x month totals")
    right.legend()
    right.grid(alpha=0.3)

    figure.suptitle(f"Transition test — {run.name}", fontsize=12)
    figure.tight_layout()
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"transition_{run.name}.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path


def series_figure(series_path: Path, outdir: Path, scale: str) -> Path:
    series = pd.read_parquet(series_path)
    series = series[series["scale"] == scale].copy()
    series["month_of_year"] = series.get("month_of_year", series["month"]).astype(int)
    inside = ~series["is_estimate"].astype(bool)
    observed = series[inside].groupby("month_of_year")["detections"].sum()
    estimate = series[~inside].groupby("month_of_year")["detections"].sum()

    figure, axes = plt.subplots(1, 2, figsize=(13, 5))
    together = series.groupby(["year", "month_of_year"])["detections"].sum().unstack("year")
    for year in together.columns:
        is_estimate = bool(series.loc[series["year"] == year, "is_estimate"].any())
        axes[0].plot(
            together.index,
            together[year],
            marker="o",
            ms=3,
            ls="--" if is_estimate else "-",
            alpha=0.85,
            color=ESTIMATE if is_estimate else None,
            label=f"{int(year)}{' (est.)' if is_estimate else ''}",
        )
    axes[0].set_title(f"{scale}: monthly totals by year")
    axes[0].set_xlabel("month")
    axes[0].set_ylabel("detections")
    axes[0].set_xticks(range(1, 13))
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=8, ncol=2)

    axes[1].bar(observed.index - 0.2, observed.values, width=0.4, color=OBSERVED, label="observed years")
    axes[1].bar(estimate.index + 0.2, estimate.values, width=0.4, color=ESTIMATE, label="backcast years")
    axes[1].set_title("Same calendar month, summed over years")
    axes[1].set_xlabel("month")
    axes[1].set_xticks(range(1, 13))
    axes[1].grid(alpha=0.3, axis="y")
    axes[1].legend()

    figure.suptitle(f"Burning calendar — {scale}", fontsize=12)
    figure.tight_layout()
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"calendar_{scale}.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, default=None, help="Training run directory (with test_monthly.csv).")
    parser.add_argument("--series", type=Path, default=None, help="harmonized.parquet")
    parser.add_argument("--scale", default="viirs_harmonized")
    parser.add_argument("--outdir", type=Path, default=Path("outputs/figures"))
    args = parser.parse_args()

    if args.run is None and args.series is None:
        raise SystemExit("Pass --run and/or --series.")

    if args.run is not None:
        print(transition_figure(args.run, args.outdir))
    if args.series is not None:
        print(series_figure(args.series, args.outdir, args.scale))


if __name__ == "__main__":
    main()
