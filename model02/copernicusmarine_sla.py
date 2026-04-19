from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import xarray as xr

try:
    import copernicusmarine
    from copernicusmarine.catalogue_parser.models import DatasetNotFound
    from copernicusmarine.core_functions.credentials_utils import (
        CouldNotConnectToAuthenticationSystem,
        InvalidUsernameOrPassword,
    )
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "copernicusmarine is not installed. Run `pip install -r requirements.txt` first."
    ) from exc

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "matplotlib is not installed. Run `pip install -r requirements.txt` first."
    ) from exc


DEFAULT_DATASET_ID = "cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D"
DEFAULT_VARIABLES = ("sla", "adt")
DEFAULT_MIN_LON = -72.0
DEFAULT_MAX_LON = -64.0
DEFAULT_MIN_LAT = 41.0
DEFAULT_MAX_LAT = 48.0
DEFAULT_START = "1993-01-01"
DEFAULT_END = "2024-12-31"
DEFAULT_OUTPUT_DIR = Path("data/copernicusmarine")
DEFAULT_PLOT_DIR = Path("plots/copernicusmarine")
DEFAULT_OUTPUT_FILENAME = "gulf_of_maine_sla.nc"
DEFAULT_CREDENTIALS_FILE = Path.home() / ".copernicusmarine" / ".copernicusmarine-credentials"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download Copernicus Marine Gulf of Maine SLA/ADT data and generate "
            "quick-look plots."
        )
    )
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument(
        "--variables",
        nargs="+",
        default=list(DEFAULT_VARIABLES),
        help="Variables to request. Default: sla adt.",
    )
    parser.add_argument("--minimum-longitude", type=float, default=DEFAULT_MIN_LON)
    parser.add_argument("--maximum-longitude", type=float, default=DEFAULT_MAX_LON)
    parser.add_argument("--minimum-latitude", type=float, default=DEFAULT_MIN_LAT)
    parser.add_argument("--maximum-latitude", type=float, default=DEFAULT_MAX_LAT)
    parser.add_argument("--start-datetime", default=DEFAULT_START)
    parser.add_argument("--end-datetime", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--output-filename", default=DEFAULT_OUTPUT_FILENAME)
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=None,
        help=(
            "Optional Copernicus Marine credentials file. Defaults to the client "
            "configuration if present."
        ),
    )
    return parser.parse_args(argv)


def validate_bounds(args: argparse.Namespace) -> None:
    if args.minimum_longitude >= args.maximum_longitude:
        raise SystemExit("--minimum-longitude must be smaller than --maximum-longitude.")
    if args.minimum_latitude >= args.maximum_latitude:
        raise SystemExit("--minimum-latitude must be smaller than --maximum-latitude.")


def find_coord_name(ds: xr.Dataset, candidates: list[str]) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(f"Could not find any of {candidates} in dataset coordinates.")


def find_var_name(ds: xr.Dataset, preferred: str) -> str:
    if preferred in ds.data_vars:
        return preferred
    lowered = {name.lower(): name for name in ds.data_vars}
    if preferred.lower() in lowered:
        return lowered[preferred.lower()]
    raise KeyError(f"Variable {preferred!r} not found. Available: {list(ds.data_vars)}")


def resolve_credentials(
    credentials_file: Path | None,
) -> tuple[str | None, str | None, Path | None]:
    username = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME")
    password = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")

    if username and password:
        return username, password, None

    if credentials_file is not None:
        return None, None, credentials_file

    if DEFAULT_CREDENTIALS_FILE.exists():
        return None, None, DEFAULT_CREDENTIALS_FILE

    return None, None, None


def download_subset(args: argparse.Namespace) -> Path:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / args.output_filename
    username, password, credentials_file = resolve_credentials(args.credentials_file)
    if username is None and password is None and credentials_file is None:
        raise SystemExit(
            "Copernicus credentials are required. Set "
            "COPERNICUSMARINE_SERVICE_USERNAME and "
            "COPERNICUSMARINE_SERVICE_PASSWORD, or pass --credentials-file."
        )
    try:
        copernicusmarine.subset(
            dataset_id=args.dataset_id,
            username=username,
            password=password,
            variables=list(args.variables),
            minimum_longitude=args.minimum_longitude,
            maximum_longitude=args.maximum_longitude,
            minimum_latitude=args.minimum_latitude,
            maximum_latitude=args.maximum_latitude,
            start_datetime=args.start_datetime,
            end_datetime=args.end_datetime,
            output_directory=str(args.output_dir),
            output_filename=args.output_filename,
            credentials_file=credentials_file,
            disable_progress_bar=True,
            overwrite=True,
        )
    except DatasetNotFound as exc:
        raise SystemExit(
            "The requested Copernicus dataset ID was not found in the live catalogue. "
            "The current default is "
            f"{DEFAULT_DATASET_ID}."
        ) from exc
    except InvalidUsernameOrPassword as exc:
        raise SystemExit(
            "Copernicus authentication failed. Check the username/password in "
            "your credentials file or environment variables."
        ) from exc
    except CouldNotConnectToAuthenticationSystem as exc:
        raise SystemExit(
            "Copernicus authentication could not be reached. Check network access "
            "to the Copernicus authentication service and try again."
        ) from exc
    if not output_path.exists():
        raise FileNotFoundError(f"Expected output file was not created: {output_path}")
    return output_path


def infer_units(data_array: xr.DataArray, fallback: str) -> str:
    return str(data_array.attrs.get("units", fallback))


def area_mean_series(data_array: xr.DataArray, lat_name: str, lon_name: str) -> xr.DataArray:
    weights = np.cos(np.deg2rad(data_array[lat_name]))
    weighted = data_array.weighted(weights)
    return weighted.mean(dim=(lat_name, lon_name), skipna=True)


def save_mean_map(
    ds: xr.Dataset,
    *,
    variable_name: str,
    time_name: str,
    lat_name: str,
    lon_name: str,
    output_dir: Path,
) -> Path:
    data_array = ds[variable_name].mean(dim=time_name, skipna=True)
    fig, ax = plt.subplots(figsize=(8, 6))
    mesh = ax.pcolormesh(ds[lon_name], ds[lat_name], data_array, shading="auto", cmap="RdBu_r")
    ax.set_title(f"{variable_name.upper()} temporal mean")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    fig.colorbar(mesh, ax=ax, label=infer_units(ds[variable_name], "m"))
    fig.tight_layout()
    path = output_dir / f"{variable_name}_mean_map.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_std_map(
    ds: xr.Dataset,
    *,
    variable_name: str,
    time_name: str,
    lat_name: str,
    lon_name: str,
    output_dir: Path,
) -> Path:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Degrees of freedom <= 0 for slice.",
            category=RuntimeWarning,
        )
        data_array = ds[variable_name].std(dim=time_name, skipna=True)
    fig, ax = plt.subplots(figsize=(8, 6))
    mesh = ax.pcolormesh(ds[lon_name], ds[lat_name], data_array, shading="auto", cmap="viridis")
    ax.set_title(f"{variable_name.upper()} temporal std. dev.")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    fig.colorbar(mesh, ax=ax, label=infer_units(ds[variable_name], "m"))
    fig.tight_layout()
    path = output_dir / f"{variable_name}_std_map.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_area_mean_timeseries(
    ds: xr.Dataset,
    *,
    variable_name: str,
    time_name: str,
    lat_name: str,
    lon_name: str,
    output_dir: Path,
) -> Path:
    series = area_mean_series(ds[variable_name], lat_name, lon_name)
    rolling = series.rolling({time_name: 30}, center=True, min_periods=15).mean()
    time_values = pd.to_datetime(ds[time_name].values)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(time_values, series.values, color="#4C78A8", linewidth=0.8, alpha=0.45, label="Daily")
    ax.plot(time_values, rolling.values, color="#F58518", linewidth=1.6, label="30-day mean")
    ax.set_title(f"Gulf of Maine area-mean {variable_name.upper()}")
    ax.set_xlabel("Time")
    ax.set_ylabel(infer_units(ds[variable_name], "m"))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = output_dir / f"{variable_name}_area_mean_timeseries.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_summary(ds: xr.Dataset, *, time_name: str, lat_name: str, lon_name: str, output_dir: Path) -> Path:
    rows: list[dict[str, object]] = []
    for variable_name, data_array in ds.data_vars.items():
        if time_name not in data_array.dims:
            continue
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Degrees of freedom <= 0 for slice.",
                category=RuntimeWarning,
            )
            std_value = float(data_array.std(skipna=True).item())
        rows.append(
            {
                "variable": variable_name,
                "time_start": pd.to_datetime(ds[time_name].values[0]).strftime("%Y-%m-%d"),
                "time_end": pd.to_datetime(ds[time_name].values[-1]).strftime("%Y-%m-%d"),
                "time_steps": int(ds.sizes[time_name]),
                "latitude_points": int(ds.sizes[lat_name]),
                "longitude_points": int(ds.sizes[lon_name]),
                "mean": float(data_array.mean(skipna=True).item()),
                "std": std_value,
                "min": float(data_array.min(skipna=True).item()),
                "max": float(data_array.max(skipna=True).item()),
                "units": infer_units(data_array, "unknown"),
            }
        )
    summary = pd.DataFrame(rows)
    numeric_columns = ["mean", "std", "min", "max"]
    summary[numeric_columns] = summary[numeric_columns].round(6)
    path = output_dir / "gulf_of_maine_sla_summary.csv"
    summary.to_csv(path, index=False)
    return path


def generate_plots(dataset_path: Path, plot_dir: Path) -> list[Path]:
    plot_dir.mkdir(parents=True, exist_ok=True)
    ds = xr.open_dataset(dataset_path)
    try:
        time_name = find_coord_name(ds, ["time"])
        lat_name = find_coord_name(ds, ["latitude", "lat", "y"])
        lon_name = find_coord_name(ds, ["longitude", "lon", "x"])

        saved_paths: list[Path] = []
        for requested_name in DEFAULT_VARIABLES:
            variable_name = find_var_name(ds, requested_name)
            saved_paths.append(
                save_mean_map(
                    ds,
                    variable_name=variable_name,
                    time_name=time_name,
                    lat_name=lat_name,
                    lon_name=lon_name,
                    output_dir=plot_dir,
                )
            )
            saved_paths.append(
                save_std_map(
                    ds,
                    variable_name=variable_name,
                    time_name=time_name,
                    lat_name=lat_name,
                    lon_name=lon_name,
                    output_dir=plot_dir,
                )
            )
            saved_paths.append(
                save_area_mean_timeseries(
                    ds,
                    variable_name=variable_name,
                    time_name=time_name,
                    lat_name=lat_name,
                    lon_name=lon_name,
                    output_dir=plot_dir,
                )
            )
        saved_paths.append(
            save_summary(
                ds,
                time_name=time_name,
                lat_name=lat_name,
                lon_name=lon_name,
                output_dir=plot_dir,
            )
        )
        return saved_paths
    finally:
        ds.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_bounds(args)
    dataset_path = download_subset(args)
    generate_plots(dataset_path, args.plot_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
