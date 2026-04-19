from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "matplotlib is not installed. Run `pip install -r requirements.txt` first."
    ) from exc


DEFAULT_INPUT = Path("data/neracoos_salinity_1950_present.csv")
DEFAULT_OUTPUT_DIR = Path("plots/salinity")
DEFAULT_STATIONS = ("B01", "E01", "F01", "M01", "N01")
DEFAULT_CHUNKSIZE = 250_000
GOOD_QC_VALUE = 1.0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run baseline analysis on the combined NERACOOS salinity CSV and "
            "generate summary plots."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input salinity CSV. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Plot output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--stations",
        nargs="+",
        default=list(DEFAULT_STATIONS),
        help="Stations to include. Default: B01 E01 F01 M01 N01.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"CSV read chunk size. Default: {DEFAULT_CHUNKSIZE}.",
    )
    return parser.parse_args(argv)


def normalize_station(station: str) -> str:
    return station.strip().upper()


def load_salinity_data(
    input_path: Path,
    *,
    stations: Sequence[str],
    chunksize: int,
) -> tuple[pd.DataFrame, dict[str, int], dict[str, int]]:
    station_filter = {normalize_station(station) for station in stations}
    raw_counts = {station: 0 for station in sorted(station_filter)}
    kept_counts = {station: 0 for station in sorted(station_filter)}
    frames: list[pd.DataFrame] = []

    usecols = [
        "station",
        "time",
        "depth",
        "latitude",
        "longitude",
        "salinity",
        "salinity_qc_agg",
    ]
    dtypes = {
        "station": "string",
        "depth": "float32",
        "latitude": "float32",
        "longitude": "float32",
        "salinity": "float32",
        "salinity_qc_agg": "float32",
    }

    for chunk in pd.read_csv(input_path, usecols=usecols, dtype=dtypes, chunksize=chunksize):
        chunk["station"] = chunk["station"].astype("string").str.upper().str.strip()
        chunk = chunk[chunk["station"].isin(station_filter)].copy()
        if chunk.empty:
            continue

        station_counts = chunk["station"].value_counts()
        for station, count in station_counts.items():
            raw_counts[str(station)] = raw_counts.get(str(station), 0) + int(count)

        chunk["time"] = pd.to_datetime(chunk["time"], utc=True, errors="coerce")
        chunk = chunk[
            chunk["time"].notna()
            & np.isfinite(chunk["salinity"])
            & (chunk["salinity_qc_agg"] == GOOD_QC_VALUE)
        ].copy()
        if chunk.empty:
            continue

        kept_station_counts = chunk["station"].value_counts()
        for station, count in kept_station_counts.items():
            kept_counts[str(station)] = kept_counts.get(str(station), 0) + int(count)

        frames.append(
            chunk[
                ["station", "time", "depth", "latitude", "longitude", "salinity"]
            ]
        )

    if not frames:
        return (
            pd.DataFrame(
                columns=["station", "time", "depth", "latitude", "longitude", "salinity"]
            ),
            raw_counts,
            kept_counts,
        )

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["station", "time", "depth"], kind="stable")
    combined["station"] = combined["station"].astype("category")
    return combined.reset_index(drop=True), raw_counts, kept_counts


def build_summary(
    data: pd.DataFrame,
    *,
    raw_counts: dict[str, int],
    kept_counts: dict[str, int],
) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()

    grouped = data.groupby("station", observed=True)
    summary = grouped.agg(
        observation_count=("salinity", "size"),
        first_time=("time", "min"),
        last_time=("time", "max"),
        latitude=("latitude", "median"),
        longitude=("longitude", "median"),
        min_depth=("depth", "min"),
        max_depth=("depth", "max"),
        mean_salinity=("salinity", "mean"),
        median_salinity=("salinity", "median"),
        std_salinity=("salinity", "std"),
        min_salinity=("salinity", "min"),
        max_salinity=("salinity", "max"),
    )

    quantiles = (
        grouped["salinity"]
        .quantile([0.05, 0.95])
        .unstack()
        .rename(columns={0.05: "salinity_p05", 0.95: "salinity_p95"})
    )
    summary = summary.join(quantiles)

    summary["raw_row_count"] = pd.Series(
        [raw_counts.get(str(station), 0) for station in summary.index],
        index=summary.index,
        dtype="int64",
    )
    summary["kept_row_count"] = pd.Series(
        [kept_counts.get(str(station), 0) for station in summary.index],
        index=summary.index,
        dtype="int64",
    )
    summary["kept_fraction"] = np.where(
        summary["raw_row_count"] > 0,
        summary["kept_row_count"] / summary["raw_row_count"],
        np.nan,
    )
    summary["timespan_days"] = (
        summary["last_time"] - summary["first_time"]
    ) / pd.Timedelta(days=1)

    summary = summary.reset_index()
    summary["first_time"] = summary["first_time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    summary["last_time"] = summary["last_time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    numeric_columns = [
        "latitude",
        "longitude",
        "min_depth",
        "max_depth",
        "mean_salinity",
        "median_salinity",
        "std_salinity",
        "min_salinity",
        "salinity_p05",
        "salinity_p95",
        "max_salinity",
        "kept_fraction",
        "timespan_days",
    ]
    summary[numeric_columns] = summary[numeric_columns].round(4)
    return summary


def save_summary_files(
    summary: pd.DataFrame,
    output_dir: Path,
    *,
    filtered_rows: int,
    generated_at: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "baseline_summary.csv", index=False)

    lines = [
        "# Sojs Salinity Baseline Summary",
        "",
        f"- Generated at: {generated_at}",
        f"- Filtered observations used: {filtered_rows:,}",
        f"- Stations: {', '.join(summary['station'].astype(str).tolist()) if not summary.empty else 'none'}",
        f"- QC filter: salinity_qc_agg == {GOOD_QC_VALUE:g}",
        "",
    ]
    if summary.empty:
        lines.append("No rows matched the requested station set and QC filter.")
    else:
        lines.extend(
            [
                "| Station | Rows | First Time | Last Time | Mean Salinity | Median Salinity | Std Dev | Depth Range |",
                "| --- | ---: | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for row in summary.itertuples(index=False):
            lines.append(
                f"| {row.station} | {row.observation_count:,} | {row.first_time} | "
                f"{row.last_time} | {row.mean_salinity:.3f} | {row.median_salinity:.3f} | "
                f"{row.std_salinity:.3f} | {row.min_depth:.1f} to {row.max_depth:.1f} m |"
            )

    (output_dir / "baseline_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def monthly_station_series(data: pd.DataFrame) -> pd.DataFrame:
    monthly = (
        data.set_index("time")
        .groupby("station", observed=True)["salinity"]
        .resample("MS")
        .mean()
        .reset_index()
    )
    monthly["rolling_12m"] = (
        monthly.groupby("station", observed=True)["salinity"]
        .transform(lambda series: series.rolling(12, min_periods=3).mean())
    )
    return monthly


def seasonal_cycle(data: pd.DataFrame) -> pd.DataFrame:
    seasonal = (
        data.assign(month=data["time"].dt.month)
        .groupby(["station", "month"], observed=True)["salinity"]
        .agg(["mean", "median", "std"])
        .reset_index()
    )
    return seasonal


def depth_profile(data: pd.DataFrame) -> pd.DataFrame:
    profile = (
        data.assign(depth_bin=data["depth"].round(1))
        .groupby(["station", "depth_bin"], observed=True)["salinity"]
        .agg(["mean", "median", "count"])
        .reset_index()
    )
    return profile[profile["count"] >= 24].copy()


def plot_combined_monthly(monthly: pd.DataFrame, output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(14, 7))
    for station, station_data in monthly.groupby("station", observed=True):
        ax.plot(
            station_data["time"],
            station_data["salinity"],
            alpha=0.22,
            linewidth=1.0,
        )
        ax.plot(
            station_data["time"],
            station_data["rolling_12m"],
            linewidth=2.0,
            label=str(station),
        )

    ax.set_title("Monthly Mean Salinity by Station")
    ax.set_xlabel("Time")
    ax.set_ylabel("Salinity")
    ax.grid(alpha=0.25)
    ax.legend(title="Station", ncol=3)
    fig.tight_layout()
    fig.savefig(output_dir / "station_monthly_mean_overlay.png", dpi=160)
    plt.close(fig)


def plot_combined_boxplot(data: pd.DataFrame, output_dir: Path) -> None:
    stations = sorted(data["station"].astype(str).unique())
    box_data = [
        data.loc[data["station"].astype(str) == station, "salinity"].to_numpy()
        for station in stations
    ]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.boxplot(box_data, tick_labels=stations, showfliers=False)
    ax.set_title("Salinity Distribution by Station")
    ax.set_xlabel("Station")
    ax.set_ylabel("Salinity")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_dir / "station_salinity_boxplot.png", dpi=160)
    plt.close(fig)


def plot_station_monthly(monthly: pd.DataFrame, station_dir: Path, station: str) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(monthly["time"], monthly["salinity"], alpha=0.25, linewidth=1.0, label="Monthly mean")
    ax.plot(monthly["time"], monthly["rolling_12m"], linewidth=2.0, label="12-month rolling mean")
    ax.set_title(f"{station} Monthly Mean Salinity")
    ax.set_xlabel("Time")
    ax.set_ylabel("Salinity")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(station_dir / "monthly_mean_salinity.png", dpi=160)
    plt.close(fig)


def plot_station_seasonal(seasonal: pd.DataFrame, station_dir: Path, station: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(seasonal["month"], seasonal["mean"], marker="o", linewidth=2.0, label="Mean")
    ax.plot(seasonal["month"], seasonal["median"], marker="s", linewidth=1.5, label="Median")
    ax.fill_between(
        seasonal["month"],
        seasonal["mean"] - seasonal["std"].fillna(0.0),
        seasonal["mean"] + seasonal["std"].fillna(0.0),
        alpha=0.2,
        label="±1 std",
    )
    ax.set_title(f"{station} Seasonal Salinity Cycle")
    ax.set_xlabel("Month")
    ax.set_ylabel("Salinity")
    ax.set_xticks(range(1, 13))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(station_dir / "seasonal_cycle.png", dpi=160)
    plt.close(fig)


def plot_station_depth_profile(profile: pd.DataFrame, station_dir: Path, station: str) -> None:
    fig, ax = plt.subplots(figsize=(7, 8))
    ax.plot(profile["mean"], profile["depth_bin"], linewidth=2.0, label="Mean")
    ax.plot(profile["median"], profile["depth_bin"], linewidth=1.5, label="Median")
    ax.set_title(f"{station} Salinity by Depth")
    ax.set_xlabel("Salinity")
    ax.set_ylabel("Depth (m)")
    ax.invert_yaxis()
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(station_dir / "depth_profile.png", dpi=160)
    plt.close(fig)


def generate_plots(data: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    monthly = monthly_station_series(data)
    seasonal = seasonal_cycle(data)
    profile = depth_profile(data)

    plot_combined_monthly(monthly, output_dir)
    plot_combined_boxplot(data, output_dir)

    for station in sorted(data["station"].astype(str).unique()):
        station_dir = output_dir / station.lower()
        station_dir.mkdir(parents=True, exist_ok=True)

        station_monthly = monthly[monthly["station"].astype(str) == station].copy()
        station_seasonal = seasonal[seasonal["station"].astype(str) == station].copy()
        station_profile = profile[profile["station"].astype(str) == station].copy()

        plot_station_monthly(station_monthly, station_dir, station)
        plot_station_seasonal(station_seasonal, station_dir, station)
        if not station_profile.empty:
            plot_station_depth_profile(station_profile, station_dir, station)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    stations = [normalize_station(station) for station in args.stations]
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    data, raw_counts, kept_counts = load_salinity_data(
        args.input,
        stations=stations,
        chunksize=args.chunksize,
    )
    if data.empty:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        save_summary_files(
            pd.DataFrame(),
            args.output_dir,
            filtered_rows=0,
            generated_at=generated_at,
        )
        print("No salinity rows matched the requested filters.")
        return 0

    summary = build_summary(data, raw_counts=raw_counts, kept_counts=kept_counts)
    save_summary_files(
        summary,
        args.output_dir,
        filtered_rows=len(data),
        generated_at=generated_at,
    )
    generate_plots(data, args.output_dir)

    print(f"Saved baseline analysis to: {args.output_dir.resolve()}")
    print(f"Stations analyzed: {', '.join(sorted(data['station'].astype(str).unique()))}")
    print(f"Filtered observations used: {len(data):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
