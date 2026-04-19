from __future__ import annotations

import argparse
import io
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence
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


BASE_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
DEFAULT_BEGIN_DATE = "19000101"
DEFAULT_END_DATE = "20241231"
DEFAULT_DATA_DIR = Path("data/coops")
DEFAULT_PLOT_DIR = Path("plots/coops")
DEFAULT_TIMEOUT_SECONDS = 90
PRODUCT = "monthly_mean"
DATUM = "MSL"
TIME_ZONE = "GMT"
UNITS = "metric"
FORMAT = "csv"
DEFAULT_STATIONS = {
    "Rockland": 8415490,
    "Portland": 8418150,
    "Bar Harbor": 8413320,
    "Eastport": 8410140,
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch NOAA CO-OPS monthly mean tide gauge records, save each station to "
            "NetCDF, and generate summary plots."
        )
    )
    parser.add_argument(
        "--begin-date",
        default=DEFAULT_BEGIN_DATE,
        help=f"Begin date in YYYYMMDD format. Default: {DEFAULT_BEGIN_DATE}.",
    )
    parser.add_argument(
        "--end-date",
        default=DEFAULT_END_DATE,
        help=f"End date in YYYYMMDD format. Default: {DEFAULT_END_DATE}.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"NetCDF output directory. Default: {DEFAULT_DATA_DIR}.",
    )
    parser.add_argument(
        "--plot-dir",
        type=Path,
        default=DEFAULT_PLOT_DIR,
        help=f"Plot output directory. Default: {DEFAULT_PLOT_DIR}.",
    )
    parser.add_argument(
        "--stations",
        nargs="+",
        default=list(DEFAULT_STATIONS),
        help=(
            "Station names to fetch. Defaults to Rockland Portland Bar Harbor "
            "Eastport."
        ),
    )
    return parser.parse_args(argv)


def normalize_station_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip())


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def canonicalize_column_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "value"


def build_url(station_id: int, begin_date: str, end_date: str) -> str:
    return (
        f"{BASE_URL}?product={PRODUCT}&station={station_id}&datum={DATUM}"
        f"&begin_date={begin_date}&end_date={end_date}&format={FORMAT}"
        f"&units={UNITS}&time_zone={TIME_ZONE}"
    )


def read_noaa_csv(url: str) -> pd.DataFrame:
    try:
        with urlopen(url, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"NOAA request failed with HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"NOAA request failed for {url}: {exc.reason}") from exc

    stripped_payload = payload.strip()
    if stripped_payload.startswith("{"):
        raise RuntimeError(f"NOAA returned JSON instead of CSV for {url}: {stripped_payload}")
    if "Error" in stripped_payload and "\n" not in stripped_payload:
        raise RuntimeError(f"NOAA returned an error for {url}: {stripped_payload}")

    def has_year_month(candidate: pd.DataFrame) -> bool:
        normalized = {canonicalize_column_name(column) for column in candidate.columns}
        return "year" in normalized and "month" in normalized

    attempts = [pd.read_csv(io.StringIO(payload))]
    lines = payload.splitlines()
    if len(lines) > 1:
        attempts.append(pd.read_csv(io.StringIO(payload), skiprows=1))

    for frame in attempts:
        frame.columns = [str(column).strip() for column in frame.columns]
        if has_year_month(frame):
            return frame

    sample = "\n".join(lines[:3])
    raise ValueError(f"Could not parse NOAA CSV columns for {url}. Sample:\n{sample}")


def parse_monthly_mean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    column_lookup = {canonicalize_column_name(column): column for column in frame.columns}
    if "year" not in column_lookup or "month" not in column_lookup:
        raise ValueError(f"Unexpected NOAA monthly_mean columns: {list(frame.columns)}")

    parsed = frame.copy()
    parsed.columns = [canonicalize_column_name(column) for column in parsed.columns]
    parsed["year"] = pd.to_numeric(parsed["year"], errors="coerce").astype("Int64")
    parsed["month"] = pd.to_numeric(parsed["month"], errors="coerce").astype("Int64")
    parsed = parsed.dropna(subset=["year", "month"]).copy()
    parsed["time"] = pd.to_datetime(
        {
            "year": parsed["year"].astype(int),
            "month": parsed["month"].astype(int),
            "day": 1,
        },
        utc=True,
        errors="coerce",
    )
    parsed = parsed.dropna(subset=["time"]).copy()

    for column in parsed.columns:
        if column in {"time"}:
            continue
        if column in {"year", "month"}:
            parsed[column] = parsed[column].astype("int64")
            continue
        parsed[column] = pd.to_numeric(parsed[column], errors="coerce")

    parsed = parsed.sort_values("time", kind="stable").reset_index(drop=True)
    return parsed


def choose_primary_series(frame: pd.DataFrame) -> str:
    candidates = [
        "msl",
        "monthly_mean",
        "monthly_mean_sea_level",
        "water_level",
        "value",
    ]
    for candidate in candidates:
        if candidate in frame.columns and frame[candidate].notna().any():
            return candidate

    numeric_columns = [
        column
        for column in frame.columns
        if column not in {"time", "year", "month"}
        and pd.api.types.is_numeric_dtype(frame[column])
        and frame[column].notna().any()
    ]
    if not numeric_columns:
        raise ValueError("No numeric monthly mean columns were found in the NOAA response.")
    return numeric_columns[0]


def frame_to_dataset(frame: pd.DataFrame, *, station_name: str, station_id: int, source_url: str) -> xr.Dataset:
    indexed = frame.set_index("time")
    data_vars: dict[str, tuple[list[str], np.ndarray, dict[str, str]]] = {}
    for column in indexed.columns:
        if column in {"year", "month"}:
            data_vars[column] = (["time"], indexed[column].to_numpy(dtype="int64"), {})
            continue
        if pd.api.types.is_numeric_dtype(indexed[column]):
            data_vars[column] = (
                ["time"],
                indexed[column].to_numpy(dtype="float64"),
                {"units": "meters"},
            )

    ds = xr.Dataset(
        data_vars=data_vars,
        coords={"time": indexed.index.to_numpy(dtype="datetime64[ns]")},
        attrs={
            "title": f"Sojs NOAA CO-OPS monthly mean tide gauge record for {station_name}",
            "station_name": station_name,
            "station_id": str(station_id),
            "product": PRODUCT,
            "datum": DATUM,
            "units": UNITS,
            "time_zone": TIME_ZONE,
            "source": "NOAA CO-OPS API",
            "source_url": source_url,
            "history": (
                "Fetched from NOAA CO-OPS and converted to NetCDF by "
                f"coops_tide_gauges.py on {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            ),
        },
    )
    ds["time"].attrs["standard_name"] = "time"
    ds["time"].attrs["long_name"] = "Month start (UTC)"
    ds["year"].attrs["long_name"] = "Calendar year"
    ds["month"].attrs["long_name"] = "Calendar month"
    return ds


def load_station_dataset(station_name: str, station_id: int, begin_date: str, end_date: str) -> xr.Dataset:
    url = build_url(station_id, begin_date, end_date)
    raw = read_noaa_csv(url)
    parsed = parse_monthly_mean_frame(raw)
    return frame_to_dataset(parsed, station_name=station_name, station_id=station_id, source_url=url)


def save_station_dataset(ds: xr.Dataset, output_dir: Path) -> Path:
    station_slug = slugify(str(ds.attrs["station_name"]))
    station_id = ds.attrs["station_id"]
    path = output_dir / f"{station_slug}_{station_id}_monthly_mean_msl.nc"
    encoding: dict[str, dict[str, object]] = {}
    for variable_name in ds.data_vars:
        if np.issubdtype(ds[variable_name].dtype, np.floating):
            encoding[variable_name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
        else:
            encoding[variable_name] = {"zlib": True, "complevel": 4}
    ds.to_netcdf(path, encoding=encoding)
    return path


def dataset_to_frame(ds: xr.Dataset) -> pd.DataFrame:
    frame = ds.to_dataframe().reset_index()
    frame["station_name"] = str(ds.attrs["station_name"])
    frame["station_id"] = str(ds.attrs["station_id"])
    frame["primary_series"] = choose_primary_series(frame)
    return frame


def combine_frames(datasets: Iterable[xr.Dataset]) -> pd.DataFrame:
    frames = [dataset_to_frame(ds) for ds in datasets]
    combined = pd.concat(frames, ignore_index=True)
    combined["value"] = np.nan
    for primary_series, group_index in combined.groupby("primary_series").groups.items():
        combined.loc[group_index, "value"] = combined.loc[group_index, primary_series]
    combined = combined.dropna(subset=["value"]).copy()
    combined["month_number"] = combined["time"].dt.month
    combined["year_number"] = combined["time"].dt.year
    return combined.sort_values(["station_name", "time"], kind="stable").reset_index(drop=True)


def save_overlay_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    for station_name, station_frame in frame.groupby("station_name", sort=True):
        ax.plot(station_frame["time"], station_frame["value"], linewidth=1.0, label=station_name)
    ax.set_title("NOAA CO-OPS Monthly Mean Sea Level")
    ax.set_xlabel("Time")
    ax.set_ylabel("Sea level relative to MSL datum (m)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = output_dir / "monthly_mean_sea_level_overlay.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_anomaly_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    for station_name, station_frame in frame.groupby("station_name", sort=True):
        anomaly = station_frame["value"] - station_frame["value"].mean()
        rolling = anomaly.rolling(window=12, min_periods=6, center=True).mean()
        ax.plot(
            station_frame["time"],
            rolling,
            linewidth=1.3,
            label=f"{station_name} (12-mo)"
        )
    ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    ax.set_title("Centered Sea-Level Anomalies")
    ax.set_xlabel("Time")
    ax.set_ylabel("Anomaly from station mean (m)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = output_dir / "monthly_mean_sea_level_anomaly_12mo.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_climatology_plot(frame: pd.DataFrame, output_dir: Path) -> Path:
    climatology = (
        frame.groupby(["station_name", "month_number"], observed=True)["value"]
        .mean()
        .reset_index()
    )
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    fig, ax = plt.subplots(figsize=(10, 5))
    for station_name, station_frame in climatology.groupby("station_name", sort=True):
        ax.plot(station_frame["month_number"], station_frame["value"], marker="o", label=station_name)
    ax.set_title("Monthly Mean Sea-Level Climatology")
    ax.set_xlabel("Month")
    ax.set_ylabel("Mean sea level (m)")
    ax.set_xticks(range(1, 13), month_labels)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = output_dir / "monthly_mean_sea_level_climatology.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_station_plots(frame: pd.DataFrame, output_dir: Path) -> list[Path]:
    saved_paths: list[Path] = []
    for station_name, station_frame in frame.groupby("station_name", sort=True):
        station_dir = output_dir / slugify(station_name)
        station_dir.mkdir(parents=True, exist_ok=True)

        rolling = station_frame["value"].rolling(window=12, min_periods=6, center=True).mean()
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(station_frame["time"], station_frame["value"], color="#4C78A8", linewidth=0.9, alpha=0.7)
        ax.plot(station_frame["time"], rolling, color="#F58518", linewidth=1.8)
        ax.set_title(f"{station_name} Monthly Mean Sea Level")
        ax.set_xlabel("Time")
        ax.set_ylabel("Sea level relative to MSL datum (m)")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        path = station_dir / "monthly_mean_sea_level.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        saved_paths.append(path)
    return saved_paths


def save_summary(frame: pd.DataFrame, output_dir: Path) -> Path:
    summary = (
        frame.groupby(["station_name", "station_id"], observed=True)
        .agg(
            first_month=("time", "min"),
            last_month=("time", "max"),
            months=("time", "size"),
            mean_msl=("value", "mean"),
            std_msl=("value", "std"),
            min_msl=("value", "min"),
            max_msl=("value", "max"),
        )
        .reset_index()
    )
    summary["first_month"] = summary["first_month"].dt.strftime("%Y-%m-%d")
    summary["last_month"] = summary["last_month"].dt.strftime("%Y-%m-%d")
    numeric_columns = ["mean_msl", "std_msl", "min_msl", "max_msl"]
    summary[numeric_columns] = summary[numeric_columns].round(4)
    path = output_dir / "coops_monthly_mean_summary.csv"
    summary.to_csv(path, index=False)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected_station_names = [normalize_station_name(name) for name in args.stations]
    station_lookup = {normalize_station_name(name): station_id for name, station_id in DEFAULT_STATIONS.items()}
    missing = [name for name in selected_station_names if name not in station_lookup]
    if missing:
        valid = ", ".join(DEFAULT_STATIONS)
        raise SystemExit(f"Unknown station(s): {', '.join(missing)}. Valid stations: {valid}.")

    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.plot_dir.mkdir(parents=True, exist_ok=True)

    datasets: list[xr.Dataset] = []
    for station_name in selected_station_names:
        station_id = station_lookup[station_name]
        datasets.append(
            load_station_dataset(
                station_name=station_name,
                station_id=station_id,
                begin_date=args.begin_date,
                end_date=args.end_date,
            )
        )

    for dataset in datasets:
        save_station_dataset(dataset, args.data_dir)

    combined = combine_frames(datasets)
    save_overlay_plot(combined, args.plot_dir)
    save_anomaly_plot(combined, args.plot_dir)
    save_climatology_plot(combined, args.plot_dir)
    save_station_plots(combined, args.plot_dir)
    save_summary(combined, args.plot_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
