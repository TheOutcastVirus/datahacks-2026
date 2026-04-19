from __future__ import annotations

import argparse
import netrc
import os
import shutil
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Sequence
from uuid import uuid4

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


DEFAULT_COLLECTION_SHORT_NAME = "TELLUS_GRFO_L3_CSR_RL06.3_OCN_v04"
DEFAULT_RAW_DIR = Path("data/grace/raw")
DEFAULT_OUTPUT_PATH = Path("data/grace/grace_ocean_mass_monthly.nc")
DEFAULT_PLOT_DIR = Path("plots/grace")
DEFAULT_GOM_MIN_LON = -72.0
DEFAULT_GOM_MAX_LON = -64.0
DEFAULT_GOM_MIN_LAT = 41.0
DEFAULT_GOM_MAX_LAT = 48.0
DEFAULT_START_DATE = "2018-05-22T00:00:00Z"
NETRC_MACHINE = "urs.earthdata.nasa.gov"
DOWNLOAD_EXTENSIONS = ".nc"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download NASA PO.DAAC GRACE monthly ocean mass grids with "
            "podaac-data-subscriber, combine them into a single NetCDF, and "
            "generate quick-look plots."
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
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help=f"Collection download start date. Default: {DEFAULT_START_DATE}.",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Optional collection download end date in ISO8601 UTC format.",
    )
    parser.add_argument(
        "--earthdata-username",
        default=None,
        help="Optional Earthdata username. Falls back to env vars or netrc.",
    )
    parser.add_argument(
        "--earthdata-password",
        default=None,
        help="Optional Earthdata password. Falls back to env vars or netrc.",
    )
    parser.add_argument(
        "--subscriber-executable",
        default=None,
        help=(
            "Optional explicit path to podaac-data-subscriber. Defaults to the "
            "copy inside the current virtual environment when available."
        ),
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Pass -f to the PO.DAAC subscriber and overwrite existing files.",
    )
    parser.add_argument(
        "--extensions",
        action="append",
        default=None,
        help=(
            "File extension regex passed through to podaac-data-subscriber. "
            "Repeat for multiple values. Default: .nc."
        ),
    )
    parser.add_argument("--gom-min-lon", type=float, default=DEFAULT_GOM_MIN_LON)
    parser.add_argument("--gom-max-lon", type=float, default=DEFAULT_GOM_MAX_LON)
    parser.add_argument("--gom-min-lat", type=float, default=DEFAULT_GOM_MIN_LAT)
    parser.add_argument("--gom-max-lat", type=float, default=DEFAULT_GOM_MAX_LAT)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.gom_min_lon >= args.gom_max_lon:
        raise SystemExit("--gom-min-lon must be smaller than --gom-max-lon.")
    if args.gom_min_lat >= args.gom_max_lat:
        raise SystemExit("--gom-min-lat must be smaller than --gom-max-lat.")


def resolve_credentials(args: argparse.Namespace) -> tuple[str, str] | None:
    username = next(
        (
            value
            for value in [
                args.earthdata_username,
                os.environ.get("EARTHDATA_USERNAME"),
                os.environ.get("NASA_EARTHDATA_USERNAME"),
            ]
            if value
        ),
        None,
    )
    password = next(
        (
            value
            for value in [
                args.earthdata_password,
                os.environ.get("EARTHDATA_PASSWORD"),
                os.environ.get("NASA_EARTHDATA_PASSWORD"),
            ]
            if value
        ),
        None,
    )
    if username and password:
        return username, password

    for name in ["_netrc", ".netrc"]:
        netrc_path = Path.home() / name
        if not netrc_path.exists():
            continue
        if netrc_path.is_dir():
            raise SystemExit(
                f"{netrc_path} exists but is a directory. Replace it with a plain "
                "text file containing your Earthdata credentials."
            )
        try:
            auth = netrc.netrc(str(netrc_path)).authenticators(NETRC_MACHINE)
        except PermissionError as exc:
            raise SystemExit(
                f"Could not read {netrc_path}. Check that it is a readable text file "
                "and not locked by another process."
            ) from exc
        except netrc.NetrcParseError as exc:
            raise SystemExit(f"Could not parse {netrc_path}: {exc}") from exc
        if auth is None:
            continue
        login, _, secret = auth
        if login and secret:
            return login, secret

    return None


def resolve_subscriber_executable(explicit: str | None) -> str:
    candidates = [explicit] if explicit else []
    helper_candidate = Path(".venv-podaac/Scripts/podaac-data-subscriber.exe")
    if helper_candidate.exists():
        candidates.append(str(helper_candidate))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        py312_candidate = (
            Path(local_appdata)
            / "Python"
            / "pythoncore-3.12-64"
            / "Scripts"
            / "podaac-data-subscriber.exe"
        )
        if py312_candidate.exists():
            candidates.append(str(py312_candidate))
    if sys_executable := shutil.which("podaac-data-subscriber"):
        candidates.append(sys_executable)
    venv_candidate = Path(".venv/Scripts/podaac-data-subscriber.exe")
    if venv_candidate.exists():
        candidates.append(str(venv_candidate))
    for candidate in candidates:
        if candidate:
            return candidate
    raise SystemExit(
        "podaac-data-subscriber is not installed. Run `pip install -r requirements.txt` first."
    )


@contextmanager
def subscriber_environment(credentials: tuple[str, str] | None) -> Iterator[dict[str, str]]:
    env = os.environ.copy()
    if credentials is None:
        yield env
        return

    username, password = credentials
    temp_root = Path.cwd() / ".tmp-auth"
    temp_root.mkdir(parents=True, exist_ok=True)
    home = temp_root / f"sojs-earthdata-{uuid4().hex}"
    home.mkdir(parents=True, exist_ok=True)
    try:
        netrc_content = (
            f"machine {NETRC_MACHINE}\nlogin {username}\npassword {password}\n"
        )
        for filename in ["_netrc", ".netrc"]:
            (home / filename).write_text(netrc_content, encoding="ascii")
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        yield env
    finally:
        shutil.rmtree(home, ignore_errors=True)


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
    existing_paths = sorted(path for path in args.raw_dir.rglob("*.nc") if path.is_file())
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
    ]
    extensions = args.extensions if args.extensions else [DOWNLOAD_EXTENSIONS]
    for extension in extensions:
        command.extend(["-e", extension])
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

    paths = sorted(path for path in args.raw_dir.rglob("*.nc") if path.is_file())
    if not paths:
        raise SystemExit(
            "podaac-data-subscriber completed but no .nc files were found under "
            f"{args.raw_dir}."
        )
    return paths


def choose_coord_name(ds: xr.Dataset, candidates: list[str]) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(f"Could not find any coordinate among {candidates}.")


def choose_primary_var(ds: xr.Dataset) -> str:
    for candidate in ["lwe_thickness", "obp", "ocean_mass", "mass", "value"]:
        if candidate in ds.data_vars:
            return candidate
    scored = sorted(
        (
            name
            for name, data_array in ds.data_vars.items()
            if len(data_array.dims) >= 2 and np.issubdtype(data_array.dtype, np.number)
        ),
        key=lambda name: len(ds[name].dims),
        reverse=True,
    )
    if not scored:
        raise KeyError(f"No gridded numeric data variable found in {list(ds.data_vars)}.")
    return scored[0]


def choose_uncertainty_var(ds: xr.Dataset) -> str | None:
    for candidate in ["uncertainty", "error", "std_error"]:
        if candidate in ds.data_vars:
            return candidate
    return None


def infer_units(data_array: xr.DataArray, fallback: str) -> str:
    return str(data_array.attrs.get("units", fallback))


def load_dataset(path: Path) -> xr.Dataset:
    ds = xr.open_dataset(path)
    time_name = choose_coord_name(ds, ["time"])
    if time_name not in ds.dims and ds[time_name].ndim == 0:
        time_value = pd.to_datetime(ds[time_name].item()).to_datetime64()
        ds = ds.drop_vars(time_name).expand_dims({time_name: [time_value]})
    return ds


def combine_datasets(paths: Sequence[Path], *, collection_short_name: str) -> xr.Dataset:
    datasets: list[xr.Dataset] = []
    try:
        for path in paths:
            datasets.append(load_dataset(path))
        if not datasets:
            raise ValueError("No GRACE files were loaded.")
        combined = xr.concat(
            datasets,
            dim="time",
            data_vars="minimal",
            coords="minimal",
            compat="override",
        )
        combined = combined.sortby("time")
        combined.load()
        combined.attrs.update(
            {
                "title": "Sojs NASA PO.DAAC GRACE monthly ocean mass grids",
                "source": "NASA PO.DAAC via podaac-data-subscriber",
                "collection_short_name": collection_short_name,
                "history": (
                    "Downloaded and combined by grace_mass_grids.py on "
                    f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
                ),
            }
        )
        return combined
    finally:
        for ds in datasets:
            ds.close()


def save_combined_dataset(ds: xr.Dataset, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoding: dict[str, dict[str, object]] = {}
    for variable_name in ds.data_vars:
        if np.issubdtype(ds[variable_name].dtype, np.floating):
            encoding[variable_name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
        else:
            encoding[variable_name] = {"zlib": True, "complevel": 4}
    ds.to_netcdf(output_path, encoding=encoding)
    return output_path


def normalize_longitudes(longitudes: xr.DataArray) -> xr.DataArray:
    return xr.where(longitudes > 180.0, longitudes - 360.0, longitudes)


def subset_bbox(
    data_array: xr.DataArray,
    *,
    lat_name: str,
    lon_name: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> xr.DataArray:
    working = data_array.assign_coords({lon_name: normalize_longitudes(data_array[lon_name])})
    working = working.sortby(lon_name).sortby(lat_name)
    return working.sel({lat_name: slice(min_lat, max_lat), lon_name: slice(min_lon, max_lon)})


def weighted_area_mean(data_array: xr.DataArray, lat_name: str, lon_name: str) -> xr.DataArray:
    weights = np.cos(np.deg2rad(data_array[lat_name]))
    return data_array.weighted(weights).mean(dim=(lat_name, lon_name), skipna=True)


def save_global_map(
    data_array: xr.DataArray,
    *,
    title: str,
    output_path: Path,
    cmap: str,
) -> Path:
    lat_name = choose_coord_name(data_array.to_dataset(name="value"), ["lat", "latitude", "y"])
    lon_name = choose_coord_name(data_array.to_dataset(name="value"), ["lon", "longitude", "x"])
    lon_values = normalize_longitudes(data_array[lon_name])
    ordered = data_array.assign_coords({lon_name: lon_values}).sortby(lon_name).sortby(lat_name)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    mesh = ax.pcolormesh(ordered[lon_name], ordered[lat_name], ordered, shading="auto", cmap=cmap)
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    fig.colorbar(mesh, ax=ax, label=infer_units(data_array, "unknown"))
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def save_area_mean_timeseries(
    data_array: xr.DataArray,
    *,
    lat_name: str,
    lon_name: str,
    plot_dir: Path,
    slug: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> Path:
    regional = subset_bbox(
        data_array,
        lat_name=lat_name,
        lon_name=lon_name,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )
    series = weighted_area_mean(regional, lat_name, lon_name)
    rolling = series.rolling(time=6, center=True, min_periods=3).mean()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(pd.to_datetime(series["time"].values), series.values, color="#4C78A8", linewidth=1.0, alpha=0.5, label="Monthly")
    ax.plot(pd.to_datetime(rolling["time"].values), rolling.values, color="#F58518", linewidth=1.8, label="6-month mean")
    ax.set_title(
        f"Gulf of Maine area-mean {slug.replace('_', ' ').title()} "
        f"({min_lon:.0f} to {max_lon:.0f} lon, {min_lat:.0f} to {max_lat:.0f} lat)"
    )
    ax.set_xlabel("Time")
    ax.set_ylabel(infer_units(data_array, "unknown"))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = plot_dir / f"{slug}_gom_area_mean_timeseries.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_monthly_heatmap(
    data_array: xr.DataArray,
    *,
    lat_name: str,
    lon_name: str,
    plot_dir: Path,
    slug: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> Path:
    regional = subset_bbox(
        data_array,
        lat_name=lat_name,
        lon_name=lon_name,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )
    series = weighted_area_mean(regional, lat_name, lon_name)
    monthly = pd.Series(series.values, index=pd.to_datetime(series["time"].values))
    anomalies = monthly - monthly.groupby(monthly.index.month).transform("mean")
    table = anomalies.groupby([anomalies.index.year, anomalies.index.month]).mean().unstack()
    table = table.reindex(columns=range(1, 13))

    fig, ax = plt.subplots(figsize=(12, 6))
    image = ax.imshow(table.values, aspect="auto", cmap="RdBu_r")
    ax.set_title(f"Gulf of Maine monthly anomalies: {slug.replace('_', ' ').title()}")
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")
    ax.set_xticks(np.arange(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(np.arange(len(table.index)))
    ax.set_yticklabels(table.index.astype(str))
    fig.colorbar(image, ax=ax, label=infer_units(data_array, "unknown"))
    fig.tight_layout()
    path = plot_dir / f"{slug}_gom_monthly_anomalies.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_summary(
    ds: xr.Dataset,
    *,
    primary_var: str,
    uncertainty_var: str | None,
    lat_name: str,
    lon_name: str,
    plot_dir: Path,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> Path:
    rows: list[dict[str, object]] = []
    for variable_name in [primary_var, uncertainty_var]:
        if variable_name is None:
            continue
        data_array = ds[variable_name]
        regional = subset_bbox(
            data_array,
            lat_name=lat_name,
            lon_name=lon_name,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        regional_mean = weighted_area_mean(regional, lat_name, lon_name)
        rows.append(
            {
                "variable": variable_name,
                "time_start": pd.to_datetime(ds["time"].values[0]).strftime("%Y-%m-%d"),
                "time_end": pd.to_datetime(ds["time"].values[-1]).strftime("%Y-%m-%d"),
                "time_steps": int(ds.sizes["time"]),
                "latitude_points": int(ds.sizes[lat_name]),
                "longitude_points": int(ds.sizes[lon_name]),
                "global_mean": float(data_array.mean(skipna=True).item()),
                "global_std": float(data_array.std(skipna=True).item()),
                "gom_mean": float(regional_mean.mean(skipna=True).item()),
                "gom_std": float(regional_mean.std(skipna=True).item()),
                "units": infer_units(data_array, "unknown"),
            }
        )
    summary = pd.DataFrame(rows)
    for column in ["global_mean", "global_std", "gom_mean", "gom_std"]:
        summary[column] = summary[column].round(6)
    path = plot_dir / "grace_ocean_mass_summary.csv"
    summary.to_csv(path, index=False)
    return path


def generate_plots(
    dataset_path: Path,
    plot_dir: Path,
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> list[Path]:
    plot_dir.mkdir(parents=True, exist_ok=True)
    ds = xr.open_dataset(dataset_path)
    try:
        lat_name = choose_coord_name(ds, ["lat", "latitude", "y"])
        lon_name = choose_coord_name(ds, ["lon", "longitude", "x"])
        primary_var = choose_primary_var(ds)
        uncertainty_var = choose_uncertainty_var(ds)

        saved: list[Path] = []
        mean_map = ds[primary_var].mean(dim="time", skipna=True)
        std_map = ds[primary_var].std(dim="time", skipna=True)
        latest_map = ds[primary_var].isel(time=-1)
        saved.append(
            save_global_map(
                mean_map,
                title=f"{primary_var} temporal mean",
                output_path=plot_dir / f"{primary_var}_mean_map.png",
                cmap="RdBu_r",
            )
        )
        saved.append(
            save_global_map(
                std_map,
                title=f"{primary_var} temporal std. dev.",
                output_path=plot_dir / f"{primary_var}_std_map.png",
                cmap="viridis",
            )
        )
        saved.append(
            save_global_map(
                latest_map,
                title=f"{primary_var} latest monthly snapshot",
                output_path=plot_dir / f"{primary_var}_latest_map.png",
                cmap="RdBu_r",
            )
        )
        saved.append(
            save_area_mean_timeseries(
                ds[primary_var],
                lat_name=lat_name,
                lon_name=lon_name,
                plot_dir=plot_dir,
                slug=primary_var,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
        )
        saved.append(
            save_monthly_heatmap(
                ds[primary_var],
                lat_name=lat_name,
                lon_name=lon_name,
                plot_dir=plot_dir,
                slug=primary_var,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
        )
        if uncertainty_var is not None:
            saved.append(
                save_global_map(
                    ds[uncertainty_var].mean(dim="time", skipna=True),
                    title=f"{uncertainty_var} temporal mean",
                    output_path=plot_dir / f"{uncertainty_var}_mean_map.png",
                    cmap="magma",
                )
            )
        saved.append(
            save_summary(
                ds,
                primary_var=primary_var,
                uncertainty_var=uncertainty_var,
                lat_name=lat_name,
                lon_name=lon_name,
                plot_dir=plot_dir,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
        )
        return saved
    finally:
        ds.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)
    paths = download_with_subscriber(args)
    combined = combine_datasets(paths, collection_short_name=args.collection_short_name)
    try:
        save_combined_dataset(combined, args.output)
    finally:
        combined.close()
    generate_plots(
        args.output,
        args.plot_dir,
        min_lat=args.gom_min_lat,
        max_lat=args.gom_max_lat,
        min_lon=args.gom_min_lon,
        max_lon=args.gom_max_lon,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
