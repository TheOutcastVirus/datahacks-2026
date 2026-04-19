from __future__ import annotations

import argparse
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import numpy as np
import pandas as pd
import xarray as xr

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "matplotlib is not installed. Run `pip install -r requirements.txt` first."
    ) from exc


DEFAULT_URL = (
    "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/"
    "norm.nao.monthly.b5001.current.ascii.table"
)
DEFAULT_DATA_DIR = Path("data/nao")
DEFAULT_PLOT_DIR = Path("plots/nao")
DEFAULT_TIMEOUT_SECONDS = 90
MONTH_COLUMNS = [str(month) for month in range(1, 13)]
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEASON_ORDER = ["DJF", "MAM", "JJA", "SON"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the CPC monthly North Atlantic Oscillation (NAO) index, save it "
            "to Sojs data artifacts, and generate quick-look plots."
        )
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Source table URL. Default: {DEFAULT_URL}.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    return parser.parse_args(argv)


def download_text(url: str) -> str:
    try:
        with urlopen(url, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"NAO request failed with HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"NAO request failed for {url}: {exc.reason}") from exc


def parse_nao_table(payload: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    wide = pd.read_csv(
        io.StringIO(payload),
        sep=r"\s+",
        header=None,
        names=["year", *MONTH_COLUMNS],
        engine="python",
    )
    wide["year"] = pd.to_numeric(wide["year"], errors="coerce")
    wide = wide.dropna(subset=["year"]).copy()
    wide["year"] = wide["year"].astype(int)
    wide = wide[wide["year"].between(1800, 2200)].copy()

    for column in MONTH_COLUMNS:
        wide[column] = pd.to_numeric(wide[column], errors="coerce")

    long = wide.melt(id_vars="year", var_name="month", value_name="nao")
    long["month"] = pd.to_numeric(long["month"], errors="coerce").astype(int)
    long = long.dropna(subset=["nao"]).copy()
    long["time"] = pd.to_datetime(
        {"year": long["year"], "month": long["month"], "day": 1},
        errors="coerce",
    )
    long = long.dropna(subset=["time"]).copy()
    long["month_name"] = pd.Categorical(
        [MONTH_LABELS[month - 1] for month in long["month"]],
        categories=MONTH_LABELS,
        ordered=True,
    )
    long = long.sort_values("time", kind="stable").reset_index(drop=True)
    return wide.reset_index(drop=True), long


def frame_to_dataset(frame: pd.DataFrame, *, source_url: str) -> xr.Dataset:
    indexed = frame.set_index("time")
    ds = xr.Dataset(
        data_vars={
            "nao": (["time"], indexed["nao"].to_numpy(dtype="float64"), {"long_name": "North Atlantic Oscillation index"}),
            "year": (["time"], indexed["year"].to_numpy(dtype="int64"), {"long_name": "Calendar year"}),
            "month": (["time"], indexed["month"].to_numpy(dtype="int64"), {"long_name": "Calendar month"}),
        },
        coords={"time": indexed.index.to_numpy(dtype="datetime64[ns]")},
        attrs={
            "title": "Sojs CPC monthly North Atlantic Oscillation index",
            "source": "NOAA CPC",
            "source_url": source_url,
            "history": (
                "Fetched from NOAA CPC and converted to NetCDF by "
                f"nao_index.py on {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            ),
        },
    )
    ds["time"].attrs["standard_name"] = "time"
    ds["time"].attrs["long_name"] = "Month start"
    return ds


def save_data_artifacts(payload: str, wide: pd.DataFrame, long: pd.DataFrame, ds: xr.Dataset, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    raw_path = output_dir / "nao_monthly_ascii_table.txt"
    raw_path.write_text(payload, encoding="utf-8")
    saved.append(raw_path)

    wide_path = output_dir / "nao_monthly_wide.csv"
    wide.to_csv(wide_path, index=False)
    saved.append(wide_path)

    monthly_path = output_dir / "nao_monthly.csv"
    long.to_csv(monthly_path, index=False)
    saved.append(monthly_path)

    netcdf_path = output_dir / "nao_monthly.nc"
    ds.to_netcdf(
        netcdf_path,
        encoding={
            "nao": {"zlib": True, "complevel": 4, "_FillValue": np.nan},
            "year": {"zlib": True, "complevel": 4},
            "month": {"zlib": True, "complevel": 4},
        },
    )
    saved.append(netcdf_path)
    return saved


def save_timeseries_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    rolling = frame["nao"].rolling(window=12, center=True, min_periods=6).mean()
    fig, ax = plt.subplots(figsize=(12, 5))
    colors = np.where(frame["nao"] >= 0.0, "#D55E00", "#0072B2")
    ax.bar(frame["time"], frame["nao"], width=25, color=colors, alpha=0.55, linewidth=0)
    ax.plot(frame["time"], rolling, color="black", linewidth=1.8, label="12-month mean")
    ax.axhline(0.0, color="black", linewidth=0.9, alpha=0.7)
    ax.set_title("Monthly NAO Index")
    ax.set_xlabel("Time")
    ax.set_ylabel("NAO")
    ax.grid(alpha=0.2, axis="y")
    ax.legend()
    fig.tight_layout()
    path = output_dir / "nao_monthly_timeseries.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_climatology_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    climatology = (
        frame.groupby("month", observed=True)["nao"]
        .agg(["mean", "std"])
        .reindex(range(1, 13))
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(climatology["month"], climatology["mean"], color="#009E73", linewidth=2.0, marker="o")
    ax.fill_between(
        climatology["month"],
        climatology["mean"] - climatology["std"],
        climatology["mean"] + climatology["std"],
        color="#009E73",
        alpha=0.2,
        linewidth=0,
    )
    ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    ax.set_title("NAO Monthly Climatology")
    ax.set_xlabel("Month")
    ax.set_ylabel("NAO")
    ax.set_xticks(range(1, 13), MONTH_LABELS)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    path = output_dir / "nao_monthly_climatology.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_heatmap_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    seasonal = frame.copy()
    seasonal["season"] = seasonal["month"].map(
        {
            12: "DJF",
            1: "DJF",
            2: "DJF",
            3: "MAM",
            4: "MAM",
            5: "MAM",
            6: "JJA",
            7: "JJA",
            8: "JJA",
            9: "SON",
            10: "SON",
            11: "SON",
        }
    )
    seasonal["season_year"] = seasonal["year"] + (seasonal["month"] == 12).astype(int)
    table = (
        seasonal.groupby(["season_year", "season"], observed=True)["nao"]
        .mean()
        .unstack()
        .reindex(columns=SEASON_ORDER)
    )
    table = table.dropna(how="all")
    finite_values = table.to_numpy(dtype=float)
    if np.isfinite(finite_values).any():
        anomaly_abs_max = float(np.nanmax(np.abs(finite_values)))
        if anomaly_abs_max == 0.0:
            anomaly_abs_max = 1.0
    else:
        anomaly_abs_max = 1.0

    fig_height = max(5.0, len(table.index) * 0.18)
    fig, ax = plt.subplots(figsize=(7, fig_height))
    image = ax.imshow(
        table.values,
        aspect="auto",
        cmap="RdBu_r",
        vmin=-anomaly_abs_max,
        vmax=anomaly_abs_max,
    )
    ax.set_title("NAO Seasonal Mean by Year")
    ax.set_xlabel("Season")
    ax.set_ylabel("Year")
    ax.set_xticks(np.arange(len(SEASON_ORDER)))
    ax.set_xticklabels(SEASON_ORDER)

    year_step = max(1, len(table.index) // 20)
    y_positions = np.arange(0, len(table.index), year_step)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(table.index.to_numpy()[y_positions].astype(str))

    fig.colorbar(image, ax=ax, label="Seasonal mean NAO")
    fig.tight_layout()
    path = output_dir / "nao_seasonal_heatmap.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_annual_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    annual = frame.groupby("year", observed=True)["nao"].mean().reset_index()
    annual["rolling_5y"] = annual["nao"].rolling(window=5, center=True, min_periods=3).mean()

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = np.where(annual["nao"] >= 0.0, "#D55E00", "#0072B2")
    ax.bar(annual["year"], annual["nao"], color=colors, alpha=0.6, width=0.85, linewidth=0)
    ax.plot(annual["year"], annual["rolling_5y"], color="black", linewidth=2.0, label="5-year mean")
    ax.axhline(0.0, color="black", linewidth=0.9, alpha=0.7)
    ax.set_title("Annual Mean NAO")
    ax.set_xlabel("Year")
    ax.set_ylabel("NAO")
    ax.grid(alpha=0.2, axis="y")
    ax.legend()
    fig.tight_layout()
    path = output_dir / "nao_annual_mean.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_winter_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    winter = frame[frame["month"].isin([12, 1, 2])].copy()
    winter["winter_year"] = winter["year"] + (winter["month"] == 12).astype(int)
    winter = (
        winter.groupby("winter_year", observed=True)["nao"]
        .mean()
        .reset_index()
        .rename(columns={"winter_year": "year", "nao": "winter_nao"})
    )
    winter["rolling_5y"] = winter["winter_nao"].rolling(window=5, center=True, min_periods=3).mean()

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = np.where(winter["winter_nao"] >= 0.0, "#B2182B", "#2166AC")
    ax.bar(winter["year"], winter["winter_nao"], color=colors, alpha=0.65, width=0.85, linewidth=0)
    ax.plot(winter["year"], winter["rolling_5y"], color="black", linewidth=2.0, label="5-winter mean")
    ax.axhline(0.0, color="black", linewidth=0.9, alpha=0.7)
    ax.set_title("Winter (DJF) Mean NAO")
    ax.set_xlabel("Winter year")
    ax.set_ylabel("NAO")
    ax.grid(alpha=0.2, axis="y")
    ax.legend()
    fig.tight_layout()
    path = output_dir / "nao_winter_djf.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_summary(frame: pd.DataFrame, output_dir: Path) -> Path:
    strongest_positive = frame.loc[frame["nao"].idxmax()]
    strongest_negative = frame.loc[frame["nao"].idxmin()]
    summary = pd.DataFrame(
        [
            {
                "time_start": frame["time"].min().strftime("%Y-%m-%d"),
                "time_end": frame["time"].max().strftime("%Y-%m-%d"),
                "months": int(len(frame)),
                "mean_nao": round(float(frame["nao"].mean()), 4),
                "std_nao": round(float(frame["nao"].std()), 4),
                "min_nao": round(float(frame["nao"].min()), 4),
                "min_time": strongest_negative["time"].strftime("%Y-%m-%d"),
                "max_nao": round(float(frame["nao"].max()), 4),
                "max_time": strongest_positive["time"].strftime("%Y-%m-%d"),
            }
        ]
    )
    path = output_dir / "nao_summary.csv"
    summary.to_csv(path, index=False)
    return path


def generate_plots(frame: pd.DataFrame, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return [
        save_timeseries_plot(frame, output_dir),
        save_annual_plot(frame, output_dir),
        save_winter_plot(frame, output_dir),
        save_climatology_plot(frame, output_dir),
        save_heatmap_plot(frame, output_dir),
        save_summary(frame, output_dir),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = download_text(args.url)
    wide, long = parse_nao_table(payload)
    dataset = frame_to_dataset(long, source_url=args.url)
    try:
        save_data_artifacts(payload, wide, long, dataset, args.data_dir)
    finally:
        dataset.close()
    generate_plots(long, args.plot_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
