from __future__ import annotations

import argparse
import io
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

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

from grace_mass_grids import (
    resolve_credentials,
    resolve_subscriber_executable,
    subscriber_environment,
)


DEFAULT_COLLECTION_SHORT_NAME = "GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4"
DEFAULT_RAW_DIR = Path("data/greenland_mass/raw")
DEFAULT_OUTPUT_PATH = Path("data/greenland_mass/greenland_mass_timeseries.nc")
DEFAULT_PLOT_DIR = Path("plots/greenland_mass")
DEFAULT_START_DATE = "2002-04-01T00:00:00Z"
DEFAULT_EXTENSION_REGEX = ""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download the PO.DAAC Greenland GRACE/GRACE-FO mass anomaly time "
            "series, convert it to NetCDF, and generate quick-look plots."
        )
    )
    parser.add_argument(
        "--collection-short-name",
        default=DEFAULT_COLLECTION_SHORT_NAME,
        help="PO.DAAC collection short name to download.",
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--extension-regex",
        default=DEFAULT_EXTENSION_REGEX,
        help="Extension regex passed to podaac-data-subscriber. Default downloads all.",
    )
    parser.add_argument("--earthdata-username", default=None)
    parser.add_argument("--earthdata-password", default=None)
    parser.add_argument("--subscriber-executable", default=None)
    parser.add_argument("--force-download", action="store_true")
    return parser.parse_args(argv)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def sanitize_column(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower())
    return re.sub(r"_+", "_", cleaned).strip("_")


def download_with_subscriber(args: argparse.Namespace) -> list[Path]:
    subscriber = resolve_subscriber_executable(args.subscriber_executable)
    credentials = resolve_credentials(args)
    if credentials is None:
        raise SystemExit(
            "Earthdata authentication is required. Provide --earthdata-username and "
            "--earthdata-password, set EARTHDATA_USERNAME / EARTHDATA_PASSWORD, or "
            "create _netrc/.netrc in your home directory."
        )

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    existing_paths = sorted(
        path
        for path in args.raw_dir.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    )
    if existing_paths and not args.force_download:
        return existing_paths

    command = [
        subscriber,
        "-c",
        args.collection_short_name,
        "-d",
        str(args.raw_dir),
        "-sd",
        args.start_date,
        "-e",
        args.extension_regex,
    ]
    if args.end_date:
        command.extend(["-ed", args.end_date])
    if args.force_download:
        command.append("-f")

    with subscriber_environment(credentials) as env:
        result = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(
            "podaac-data-subscriber failed"
            + (f": {detail}" if detail else ".")
        )

    paths = sorted(
        path
        for path in args.raw_dir.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    )
    if not paths:
        raise SystemExit(
            f"podaac-data-subscriber completed but found no files under {args.raw_dir}."
        )
    return paths


def choose_primary_file(paths: list[Path]) -> Path:
    ranked = sorted(
        paths,
        key=lambda path: (
            path.name.endswith((".xml", ".json", ".md5", ".sha256")),
            "citation" in path.name.lower(),
            path.suffix.lower() not in {"", ".txt", ".tsv", ".csv", ".asc", ".dat"},
            len(path.name),
        ),
    )
    return ranked[0]


def load_table(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"No table rows found in {path}.")

    header_end_index = next(
        (index for index, line in enumerate(lines) if "Header_End" in line),
        None,
    )
    if header_end_index is not None:
        data_lines = lines[header_end_index + 1 :]
        frame = pd.read_csv(
            io.StringIO("\n".join(data_lines)),
            sep=r"\s+",
            engine="python",
            header=None,
            names=["time_decimal_year", "greenland_mass_gt", "greenland_mass_sigma_gt"],
        )
        return frame

    filtered = [line for line in lines if not line.lstrip().startswith("#")]
    preview = "\n".join(filtered[:10])
    delimiter = "," if preview.count(",") >= 3 else r"\s+"
    frame = pd.read_csv(io.StringIO("\n".join(filtered)), sep=delimiter, engine="python")

    if frame.columns.tolist() == list(range(len(frame.columns))):
        frame = pd.read_csv(
            io.StringIO("\n".join(filtered)),
            sep=delimiter,
            engine="python",
            header=None,
        )
        frame.columns = [f"column_{index}" for index in range(frame.shape[1])]

    frame.columns = [
        sanitize_column(column) or f"column_{index}"
        for index, column in enumerate(frame.columns)
    ]
    return frame


def decimal_year_to_datetime(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    years = np.floor(numeric).astype("Int64")
    fraction = numeric - years.astype(float)
    months = np.clip(np.floor(fraction * 12.0 + 1.0).astype("Int64"), 1, 12)
    return pd.to_datetime(
        {
            "year": years.astype("Int64"),
            "month": months.astype("Int64"),
            "day": 1,
        },
        errors="coerce",
        utc=True,
    )


def infer_time(frame: pd.DataFrame) -> tuple[pd.Series, str]:
    for column in frame.columns:
        if any(token in column for token in ["decimal", "dec", "year"]):
            parsed = decimal_year_to_datetime(frame[column])
            if parsed.notna().sum() >= max(3, len(frame) // 2):
                return parsed, column

    for column in frame.columns:
        if any(token in column for token in ["date", "time"]):
            parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
            if parsed.notna().sum() >= max(3, len(frame) // 2):
                return parsed, column

    for column in frame.columns:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().sum() < max(3, len(frame) // 2):
            continue
        if numeric.between(2000, 2126, inclusive="both").all():
            parsed = decimal_year_to_datetime(numeric)
            if parsed.notna().sum() >= max(3, len(frame) // 2):
                return parsed, column

    raise ValueError(f"Could not infer a time column from {list(frame.columns)}.")


def choose_mass_column(frame: pd.DataFrame, time_column: str) -> str:
    candidates = [
        "mass_gt",
        "mass_gigatons",
        "mass_gigatonnes",
        "cumulative_mass_gt",
        "mass_anomaly_gt",
        "greenland_mass_gt",
        "mass",
    ]
    numeric_columns = [
        column
        for column in frame.columns
        if column != time_column and pd.to_numeric(frame[column], errors="coerce").notna().any()
    ]
    for candidate in candidates:
        if candidate in numeric_columns:
            return candidate
    if not numeric_columns:
        raise ValueError("No numeric data columns were found in the Greenland mass table.")
    return numeric_columns[0]


def choose_uncertainty_column(frame: pd.DataFrame, time_column: str, mass_column: str) -> str | None:
    for candidate in [
        "uncertainty_gt",
        "uncertainty",
        "mass_uncertainty_gt",
        "mass_uncertainty",
        "greenland_mass_sigma_gt",
        "sigma",
        "error",
        "two_sigma",
    ]:
        if candidate in frame.columns and candidate not in {time_column, mass_column}:
            return candidate
    return None


def frame_to_dataset(frame: pd.DataFrame, *, collection_short_name: str, source_file: Path) -> xr.Dataset:
    time_values, time_column = infer_time(frame)
    parsed = frame.copy()
    parsed["time"] = time_values
    parsed = parsed.dropna(subset=["time"]).reset_index(drop=True)

    for column in parsed.columns:
        if column == "time":
            continue
        parsed[column] = pd.to_numeric(parsed[column], errors="coerce")

    mass_column = choose_mass_column(parsed, time_column)
    uncertainty_column = choose_uncertainty_column(parsed, time_column, mass_column)

    indexed = parsed.set_index("time").sort_index()
    data_vars: dict[str, tuple[list[str], np.ndarray, dict[str, str]]] = {
        mass_column: (["time"], indexed[mass_column].to_numpy(dtype="float64"), {"units": "Gt"}),
    }
    if uncertainty_column is not None:
        data_vars[uncertainty_column] = (
            ["time"],
            indexed[uncertainty_column].to_numpy(dtype="float64"),
            {"units": "Gt"},
        )

    ds = xr.Dataset(
        data_vars=data_vars,
        coords={"time": indexed.index.to_numpy(dtype="datetime64[ns]")},
        attrs={
            "title": "Sojs Greenland ice-sheet mass anomaly time series",
            "collection_short_name": collection_short_name,
            "source": "NASA PO.DAAC via podaac-data-subscriber",
            "source_file": str(source_file),
            "mass_variable": mass_column,
            "uncertainty_variable": uncertainty_column or "",
            "history": (
                "Downloaded and converted by greenland_mass_timeseries.py on "
                f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            ),
        },
    )
    return ds


def save_dataset(ds: xr.Dataset, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoding: dict[str, dict[str, object]] = {}
    for variable_name in ds.data_vars:
        encoding[variable_name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
    ds.to_netcdf(output_path, encoding=encoding)
    return output_path


def save_timeseries_plot(ds: xr.Dataset, plot_dir: Path) -> Path:
    mass_variable = str(ds.attrs["mass_variable"])
    uncertainty_variable = str(ds.attrs.get("uncertainty_variable", "")) or None
    series = ds[mass_variable]
    rolling = series.rolling(time=6, center=True, min_periods=3).mean()
    time_values = pd.to_datetime(ds["time"].values)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(time_values, series.values, color="#2C7FB8", linewidth=1.2, label="Monthly")
    ax.plot(time_values, rolling.values, color="#D95F0E", linewidth=2.0, label="6-month mean")
    if uncertainty_variable is not None:
        uncertainty = ds[uncertainty_variable]
        ax.fill_between(
            time_values,
            series.values - uncertainty.values,
            series.values + uncertainty.values,
            color="#9ECAE1",
            alpha=0.35,
            linewidth=0,
            label="Uncertainty",
        )
    ax.set_title("Greenland ice-sheet mass anomaly")
    ax.set_xlabel("Time")
    ax.set_ylabel("Gt")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = plot_dir / "greenland_mass_timeseries.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_annual_plot(ds: xr.Dataset, plot_dir: Path) -> Path:
    mass_variable = str(ds.attrs["mass_variable"])
    monthly = pd.Series(ds[mass_variable].values, index=pd.to_datetime(ds["time"].values))
    annual = monthly.resample("YE").mean()

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(annual.index.year.astype(str), annual.values, color="#4C78A8")
    ax.set_title("Greenland annual mean mass anomaly")
    ax.set_xlabel("Year")
    ax.set_ylabel("Gt")
    ax.tick_params(axis="x", labelrotation=90)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = plot_dir / "greenland_mass_annual_mean.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_summary(ds: xr.Dataset, plot_dir: Path) -> Path:
    mass_variable = str(ds.attrs["mass_variable"])
    rows = [
        {
            "collection_short_name": ds.attrs["collection_short_name"],
            "mass_variable": mass_variable,
            "time_start": pd.to_datetime(ds["time"].values[0]).strftime("%Y-%m-%d"),
            "time_end": pd.to_datetime(ds["time"].values[-1]).strftime("%Y-%m-%d"),
            "time_steps": int(ds.sizes["time"]),
            "mean_gt": float(ds[mass_variable].mean(skipna=True).item()),
            "std_gt": float(ds[mass_variable].std(skipna=True).item()),
            "min_gt": float(ds[mass_variable].min(skipna=True).item()),
            "max_gt": float(ds[mass_variable].max(skipna=True).item()),
        }
    ]
    summary = pd.DataFrame(rows)
    for column in ["mean_gt", "std_gt", "min_gt", "max_gt"]:
        summary[column] = summary[column].round(6)
    path = plot_dir / "greenland_mass_summary.csv"
    summary.to_csv(path, index=False)
    return path


def generate_plots(ds: xr.Dataset, plot_dir: Path) -> list[Path]:
    plot_dir.mkdir(parents=True, exist_ok=True)
    return [
        save_timeseries_plot(ds, plot_dir),
        save_annual_plot(ds, plot_dir),
        save_summary(ds, plot_dir),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = download_with_subscriber(args)
    source_file = choose_primary_file(paths)
    frame = load_table(source_file)
    ds = frame_to_dataset(
        frame,
        collection_short_name=args.collection_short_name,
        source_file=source_file,
    )
    try:
        save_dataset(ds, args.output)
        generate_plots(ds, args.plot_dir)
    finally:
        ds.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
