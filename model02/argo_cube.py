from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import xarray as xr
from fsspec.exceptions import FSTimeoutError

try:
    from argopy import DataFetcher
    from argopy.errors import DataNotFound, ErddapServerError
except ImportError as exc:  # pragma: no cover - import guard for first run
    raise SystemExit(
        "argopy is not installed. Run `pip install -r requirements.txt` first."
    ) from exc


ERDDAP_CHUNKS_MAXSIZE = {
    "lon": 20,
    "lat": 20,
    "dpt": 500,
    "time": 60,
}
DEFAULT_API_TIMEOUT = 300
MAX_API_TIMEOUT = 900
DEFAULT_LON_MIN = -80.0
DEFAULT_LON_MAX = -55.0
DEFAULT_LAT_MIN = 38.0
DEFAULT_LAT_MAX = 48.0
DEFAULT_START_DATE = "1950-01-01"
DEFAULT_END_DATE = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
DEFAULT_OUTPUT = Path("data/sojs_argo_monthly_density_1950_present.nc")
ALLOWED_DATA_MODES = (b"D", b"A", "D", "A")
DEFAULT_FETCH_WINDOW_MONTHS = 12
ARGO_RECORD_START = pd.Timestamp("2001-01-01")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Gulf of Maine and NW Atlantic shelf Argo data, aggregate it to "
            "monthly gridded temperature, salinity, and density fields, and save "
            "the result to a NetCDF file."
        )
    )
    parser.add_argument(
        "--lon-min",
        type=float,
        default=DEFAULT_LON_MIN,
        help=f"Minimum longitude for the Argo query. Default: {DEFAULT_LON_MIN}.",
    )
    parser.add_argument(
        "--lon-max",
        type=float,
        default=DEFAULT_LON_MAX,
        help=f"Maximum longitude for the Argo query. Default: {DEFAULT_LON_MAX}.",
    )
    parser.add_argument(
        "--lat-min",
        type=float,
        default=DEFAULT_LAT_MIN,
        help=f"Minimum latitude for the Argo query. Default: {DEFAULT_LAT_MIN}.",
    )
    parser.add_argument(
        "--lat-max",
        type=float,
        default=DEFAULT_LAT_MAX,
        help=f"Maximum latitude for the Argo query. Default: {DEFAULT_LAT_MAX}.",
    )
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help=f"Start date for the Argo query. Default: {DEFAULT_START_DATE}.",
    )
    parser.add_argument(
        "--end-date",
        default=DEFAULT_END_DATE,
        help=f"End date for the Argo query. Default: {DEFAULT_END_DATE}.",
    )
    parser.add_argument(
        "--max-depth",
        type=float,
        default=2000.0,
        help="Maximum depth in dbar/meters to query. Default: 2000.",
    )
    parser.add_argument(
        "--depth-step",
        type=float,
        default=25.0,
        help="Vertical interpolation step for the output cube. Default: 25.",
    )
    parser.add_argument(
        "--lat-step",
        type=float,
        default=1.0,
        help="Latitude bin size in degrees for the output cube. Default: 1.",
    )
    parser.add_argument(
        "--lon-step",
        type=float,
        default=1.0,
        help="Longitude bin size in degrees for the output cube. Default: 1.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output NetCDF path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--dataset",
        default="phy",
        choices=["phy", "bgc", "bgc-s"],
        help="argopy dataset family. Default: phy.",
    )
    parser.add_argument(
        "--api-timeout",
        type=int,
        default=DEFAULT_API_TIMEOUT,
        help=f"Remote request timeout in seconds. Default: {DEFAULT_API_TIMEOUT}.",
    )
    parser.add_argument(
        "--fetch-window-months",
        type=int,
        default=DEFAULT_FETCH_WINDOW_MONTHS,
        help=(
            "Number of months to fetch per ERDDAP request when building the "
            f"historical cube. Default: {DEFAULT_FETCH_WINDOW_MONTHS}."
        ),
    )
    return parser.parse_args(argv)


def parse_timestamp(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp


def validate_bounds(
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
) -> tuple[float, float, float, float]:
    if lat_min >= lat_max:
        raise ValueError("--lat-min must be smaller than --lat-max.")
    if lon_min >= lon_max:
        raise ValueError("--lon-min must be smaller than --lon-max.")
    if not (-90.0 <= lat_min <= 90.0 and -90.0 <= lat_max <= 90.0):
        raise ValueError("Latitude bounds must stay inside [-90, 90].")
    if lon_min < -180.0 or lon_max > 180.0:
        raise ValueError("Longitude bounds must stay inside [-180, 180].")
    return lon_min, lon_max, lat_min, lat_max


def build_numeric_edges(start: float, stop: float, step: float) -> np.ndarray:
    if step <= 0:
        raise ValueError("Grid step sizes must be positive.")

    edges = np.arange(start, stop + step, step, dtype=float)
    if edges[-1] < stop:
        edges = np.append(edges, stop)
    else:
        edges[-1] = stop

    if len(edges) < 2:
        raise ValueError("At least one spatial bin is required.")
    return edges


def build_month_starts(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    if end < start:
        raise ValueError("--end-date must be later than or equal to --start-date.")

    start_month = start.to_period("M").to_timestamp()
    end_month = end.to_period("M").to_timestamp()
    months = pd.date_range(start=start_month, end=end_month, freq="MS")
    if len(months) == 0:
        raise ValueError("At least one monthly time bin is required.")
    return months


def iter_time_windows(
    start: pd.Timestamp,
    end: pd.Timestamp,
    window_months: int,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if window_months <= 0:
        raise ValueError("--fetch-window-months must be positive.")

    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    current_start = start.normalize()
    end = end.normalize()
    while current_start <= end:
        next_start = current_start + pd.DateOffset(months=window_months)
        current_end = min(next_start - pd.Timedelta(days=1), end)
        windows.append((current_start, current_end))
        current_start = current_end + pd.Timedelta(days=1)
    return windows


def bin_centers(edges: np.ndarray) -> np.ndarray:
    return (edges[:-1] + edges[1:]) / 2.0


def pick_existing_var(ds: xr.Dataset, preferred_names: list[str]) -> str:
    for name in preferred_names:
        if name in ds.variables:
            return name
    raise KeyError(f"None of the variables were found: {preferred_names}")


def timeout_candidates(api_timeout: int) -> list[int]:
    first = max(1, int(api_timeout))
    second = min(first * 2, MAX_API_TIMEOUT)
    if second == first:
        return [first]
    return [first, second]


def data_mode_mask(ds: xr.Dataset) -> xr.DataArray | None:
    if "DATA_MODE" not in ds.variables:
        return None
    return ds["DATA_MODE"].isin(ALLOWED_DATA_MODES)


def fetch_argo_profiles(
    *,
    dataset: str,
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    max_depth: float,
    start_date: str,
    end_date: str,
    api_timeout: int,
) -> xr.Dataset | None:
    box = [lon_min, lon_max, lat_min, lat_max, 0.0, max_depth, start_date, end_date]
    failures: list[str] = []

    for timeout_seconds in timeout_candidates(api_timeout):
        try:
            ds = (
                DataFetcher(
                    src="erddap",
                    ds=dataset,
                    api_timeout=timeout_seconds,
                    parallel=True,
                    chunks="auto",
                    chunks_maxsize=ERDDAP_CHUNKS_MAXSIZE,
                )
                .region(box)
                .to_xarray()
            )
            if "N_POINTS" not in ds.dims:
                raise ValueError(
                    "Expected a point-based Argo dataset with an N_POINTS dimension."
                )
            if ds.sizes.get("N_POINTS", 0) == 0:
                return None

            mask = data_mode_mask(ds)
            if mask is not None:
                ds = ds.where(mask, drop=True)

            if ds.sizes.get("N_POINTS", 0) == 0:
                return None
            return ds.argo.point2profile()
        except DataNotFound:
            return None
        except (ErddapServerError, FSTimeoutError, TimeoutError, OSError) as exc:
            failures.append(f"timeout={timeout_seconds}s: {type(exc).__name__}: {exc}")
            continue

    joined_failures = "; ".join(failures) if failures else "unknown remote fetch failure"
    raise RuntimeError(
        "Unable to fetch Argo data for this request. "
        f"Attempt summary: {joined_failures}. "
        "Try reducing the date range, lowering max_depth, or increasing api_timeout."
    )


def seawater_density_kg_m3(
    practical_salinity: np.ndarray,
    temperature_c: np.ndarray,
    pressure_dbar: np.ndarray,
) -> np.ndarray:
    salinity = np.asarray(practical_salinity, dtype=float)
    temperature = np.asarray(temperature_c, dtype=float)
    pressure_bar = np.asarray(pressure_dbar, dtype=float) / 10.0

    density = np.full(salinity.shape, np.nan, dtype=float)
    valid = (
        np.isfinite(salinity)
        & np.isfinite(temperature)
        & np.isfinite(pressure_bar)
        & (salinity >= 0.0)
    )
    if not np.any(valid):
        return density

    salinity = salinity[valid]
    temperature = temperature[valid]
    pressure_bar = pressure_bar[valid]

    t = temperature
    s = salinity
    sqrt_s = np.sqrt(s)

    rho_w = (
        999.842594
        + 6.793952e-2 * t
        - 9.095290e-3 * t**2
        + 1.001685e-4 * t**3
        - 1.120083e-6 * t**4
        + 6.536332e-9 * t**5
    )
    a = (
        0.824493
        - 4.0899e-3 * t
        + 7.6438e-5 * t**2
        - 8.2467e-7 * t**3
        + 5.3875e-9 * t**4
    )
    b = -5.72466e-3 + 1.0227e-4 * t - 1.6546e-6 * t**2
    c = 4.8314e-4
    rho0 = rho_w + a * s + b * s * sqrt_s + c * s**2

    kw = (
        19652.21
        + 148.4206 * t
        - 2.327105 * t**2
        + 1.360477e-2 * t**3
        - 5.155288e-5 * t**4
    )
    aw = 54.6746 - 0.603459 * t + 1.09987e-2 * t**2 - 6.1670e-5 * t**3
    bw = 7.944e-2 + 1.6483e-2 * t - 5.3009e-4 * t**2
    k0 = kw + aw * s + bw * s * sqrt_s

    a_p = 3.239908 + 1.43713e-3 * t + 1.16092e-4 * t**2 - 5.77905e-7 * t**3
    b_p = 2.2838e-3 - 1.0981e-5 * t - 1.6078e-6 * t**2
    c_p = 1.91075e-4
    d_p = 8.50935e-5 - 6.12293e-6 * t + 5.2787e-8 * t**2
    e_p = -9.9348e-7 + 2.0816e-8 * t + 9.1697e-10 * t**2
    secant_bulk_modulus = (
        k0
        + (a_p + b_p * s + c_p * s * sqrt_s) * pressure_bar
        + (d_p + e_p * s) * pressure_bar**2
    )

    density_valid = rho0 / (1.0 - pressure_bar / secant_bulk_modulus)
    density[valid] = density_valid
    return density


def profiles_to_grouped_sums(
    ds_profiles: xr.Dataset,
    depth_levels: np.ndarray,
    lat_edges: np.ndarray,
    lon_edges: np.ndarray,
) -> pd.DataFrame:
    pressure_axis = "PRES_ADJUSTED" if "PRES_ADJUSTED" in ds_profiles.variables else "PRES"
    temp_var = pick_existing_var(ds_profiles, ["TEMP_ADJUSTED", "TEMP"])
    sal_var = pick_existing_var(ds_profiles, ["PSAL_ADJUSTED", "PSAL"])

    ds_interp = ds_profiles.argo.interp_std_levels(
        depth_levels.tolist(),
        axis=pressure_axis,
    )
    if ds_interp is None:
        return pd.DataFrame()

    depth_dim = "PRES_INTERPOLATED"
    if depth_dim not in ds_interp.dims:
        raise ValueError("Interpolated dataset is missing the PRES_INTERPOLATED dimension.")

    n_prof = ds_interp.sizes["N_PROF"]
    n_depth = ds_interp.sizes[depth_dim]
    lat_centers = bin_centers(lat_edges)
    lon_centers = bin_centers(lon_edges)

    temperature = ds_interp[temp_var].values.reshape(-1)
    salinity = ds_interp[sal_var].values.reshape(-1)
    depth = np.tile(ds_interp[depth_dim].values.astype(float), n_prof)
    density = seawater_density_kg_m3(salinity, temperature, depth)

    df = pd.DataFrame(
        {
            "time": np.repeat(pd.to_datetime(ds_interp["TIME"].values), n_depth),
            "latitude": np.repeat(ds_interp["LATITUDE"].values.astype(float), n_depth),
            "longitude": np.repeat(ds_interp["LONGITUDE"].values.astype(float), n_depth),
            "depth": depth,
            "temperature": temperature,
            "salinity": salinity,
            "density": density,
        }
    )
    df["time"] = pd.to_datetime(df["time"])
    df = df.dropna(subset=["temperature", "salinity", "density"], how="all")
    if df.empty:
        raise ValueError("No usable Argo measurements were returned for the requested region.")

    df["time"] = df["time"].dt.to_period("M").dt.to_timestamp()
    df["lat_bin"] = pd.cut(
        df["latitude"],
        bins=lat_edges,
        labels=lat_centers,
        right=False,
        include_lowest=True,
    )
    df["lon_bin"] = pd.cut(
        df["longitude"],
        bins=lon_edges,
        labels=lon_centers,
        right=False,
        include_lowest=True,
    )
    df = df.dropna(subset=["time", "lat_bin", "lon_bin"])
    if df.empty:
        return pd.DataFrame()

    for variable in ["temperature", "salinity", "density"]:
        valid = np.isfinite(df[variable].to_numpy())
        df[f"{variable}_sum"] = np.where(valid, df[variable].to_numpy(), 0.0)
    df["sample_count"] = np.isfinite(df["density"].to_numpy()).astype(np.int32)

    grouped = (
        df.groupby(["time", "lat_bin", "lon_bin", "depth"], observed=True)
        .agg(
            temperature_sum=("temperature_sum", "sum"),
            salinity_sum=("salinity_sum", "sum"),
            density_sum=("density_sum", "sum"),
            sample_count=("sample_count", "sum"),
        )
        .reset_index()
        .rename(
            columns={
                "lat_bin": "latitude",
                "lon_bin": "longitude",
            }
        )
    )

    return grouped


def build_gridded_cube(
    grouped: pd.DataFrame,
    depth_levels: np.ndarray,
    lat_edges: np.ndarray,
    lon_edges: np.ndarray,
    month_starts: pd.DatetimeIndex,
) -> xr.Dataset:
    lat_centers = bin_centers(lat_edges)
    lon_centers = bin_centers(lon_edges)

    if grouped.empty:
        raise ValueError("No gridded Argo measurements were produced for the requested region.")

    grouped = (
        grouped.groupby(["time", "latitude", "longitude", "depth"], observed=True)
        .agg(
            temperature_sum=("temperature_sum", "sum"),
            salinity_sum=("salinity_sum", "sum"),
            density_sum=("density_sum", "sum"),
            sample_count=("sample_count", "sum"),
        )
        .reset_index()
    )
    grouped["temperature"] = grouped["temperature_sum"] / grouped["sample_count"].where(
        grouped["sample_count"] > 0
    )
    grouped["salinity"] = grouped["salinity_sum"] / grouped["sample_count"].where(
        grouped["sample_count"] > 0
    )
    grouped["density"] = grouped["density_sum"] / grouped["sample_count"].where(
        grouped["sample_count"] > 0
    )
    grouped = grouped[
        ["time", "latitude", "longitude", "depth", "temperature", "salinity", "density", "sample_count"]
    ]

    cube = grouped.set_index(["time", "latitude", "longitude", "depth"]).to_xarray()
    cube = cube.reindex(
        time=month_starts,
        latitude=lat_centers,
        longitude=lon_centers,
        depth=depth_levels,
    )
    cube = cube.transpose("time", "latitude", "longitude", "depth")
    cube["sample_count"] = cube["sample_count"].fillna(0).astype(np.int32)

    cube["temperature"].attrs.update(
        long_name="Monthly mean Argo temperature",
        units="degree_Celsius",
    )
    cube["salinity"].attrs.update(
        long_name="Monthly mean Argo practical salinity",
    )
    cube["density"].attrs.update(
        long_name="Monthly mean Argo in-situ seawater density",
        units="kg m-3",
    )
    cube["sample_count"].attrs.update(
        long_name="Number of interpolated Argo samples contributing to each monthly cell",
    )
    cube["time"].attrs["long_name"] = "month start"
    cube["latitude"].attrs["units"] = "degrees_north"
    cube["longitude"].attrs["units"] = "degrees_east"
    cube["depth"].attrs["units"] = "dbar"

    return cube


def save_cube(
    cube: xr.Dataset,
    output_path: Path,
    *,
    dataset: str,
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    max_depth: float,
    start_date: str,
    end_date: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cube.attrs.update(
        title="Sojs monthly Argo temperature, salinity, and density cube",
        summary=(
            "Monthly gridded Argo temperature, salinity, and density derived from "
            "quality-controlled delayed-mode and adjusted-mode profile observations "
            "interpolated to standard depth levels."
        ),
        source=f"argopy/erddap/{dataset}",
        longitude_min=lon_min,
        longitude_max=lon_max,
        latitude_min=lat_min,
        latitude_max=lat_max,
        max_depth=max_depth,
        time_start=start_date,
        time_end=end_date,
        aggregation="monthly",
        data_mode_filter="A,D",
        history=(
            f"{datetime.now(UTC).replace(microsecond=0).isoformat()} "
            "generated by Sojs argo_cube.py"
        ),
    )
    cube.to_netcdf(output_path)


def run_argo_query(
    *,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    output: str | Path = DEFAULT_OUTPUT,
    lon_min: float = DEFAULT_LON_MIN,
    lon_max: float = DEFAULT_LON_MAX,
    lat_min: float = DEFAULT_LAT_MIN,
    lat_max: float = DEFAULT_LAT_MAX,
    max_depth: float = 2000.0,
    depth_step: float = 25.0,
    lat_step: float = 1.0,
    lon_step: float = 1.0,
    dataset: str = "phy",
    api_timeout: int = DEFAULT_API_TIMEOUT,
    fetch_window_months: int = DEFAULT_FETCH_WINDOW_MONTHS,
) -> xr.Dataset:
    output_path = Path(output)

    start_ts = parse_timestamp(start_date)
    end_ts = parse_timestamp(end_date)
    lon_min, lon_max, lat_min, lat_max = validate_bounds(
        lon_min,
        lon_max,
        lat_min,
        lat_max,
    )
    lat_edges = build_numeric_edges(lat_min, lat_max, lat_step)
    lon_edges = build_numeric_edges(lon_min, lon_max, lon_step)
    month_starts = build_month_starts(start_ts, end_ts)
    fetch_start_ts = max(start_ts, ARGO_RECORD_START)
    if fetch_start_ts > end_ts:
        raise ValueError(
            "The requested period ends before the Argo record begins, so no Argo cube can be built."
        )
    time_windows = iter_time_windows(fetch_start_ts, end_ts, fetch_window_months)
    depth_levels = np.arange(0.0, max_depth + depth_step, depth_step)
    if len(depth_levels) < 2:
        raise ValueError("The requested depth range produced no depth bins.")

    if start_ts < ARGO_RECORD_START:
        print(
            "Requested time axis starts before the Argo record; "
            f"remote fetches will begin at {ARGO_RECORD_START.strftime('%Y-%m-%d')} "
            "and earlier months will remain empty in the output cube."
        )

    grouped_frames: list[pd.DataFrame] = []
    for window_start, window_end in time_windows:
        window_start_str = window_start.strftime("%Y-%m-%d")
        window_end_str = window_end.strftime("%Y-%m-%d")
        print(f"Fetching Argo data for {window_start_str} to {window_end_str}...")
        ds_profiles = fetch_argo_profiles(
            dataset=dataset,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
            max_depth=max_depth,
            start_date=window_start_str,
            end_date=window_end_str,
            api_timeout=api_timeout,
        )
        if ds_profiles is None:
            print("  No delayed-mode or adjusted-mode Argo data in this window.")
            continue

        grouped = profiles_to_grouped_sums(
            ds_profiles=ds_profiles,
            depth_levels=depth_levels,
            lat_edges=lat_edges,
            lon_edges=lon_edges,
        )
        if grouped.empty:
            print("  Data fetched, but no records landed in the output grid.")
            continue

        grouped_frames.append(grouped)
        print(f"  Added {len(grouped):,} populated monthly grid cells from this window.")

    if not grouped_frames:
        raise ValueError("No usable Argo measurements were produced for the requested query.")

    cube = build_gridded_cube(
        grouped=pd.concat(grouped_frames, ignore_index=True),
        depth_levels=depth_levels,
        lat_edges=lat_edges,
        lon_edges=lon_edges,
        month_starts=month_starts,
    )
    save_cube(
        cube,
        output_path,
        dataset=dataset,
        lon_min=lon_min,
        lon_max=lon_max,
        lat_min=lat_min,
        lat_max=lat_max,
        max_depth=max_depth,
        start_date=start_date,
        end_date=end_date,
    )

    print(f"Saved NetCDF cube to: {output_path.resolve()}")
    print(
        "Dimensions: "
        f"time={cube.sizes['time']}, "
        f"latitude={cube.sizes['latitude']}, "
        f"longitude={cube.sizes['longitude']}, "
        f"depth={cube.sizes['depth']}"
    )
    return cube


def running_inside_ipykernel() -> bool:
    return "ipykernel" in sys.modules


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv and running_inside_ipykernel():
        print(
            "This script is a CLI when run as a program, but inside Jupyter you should "
            "call run_argo_query(...).\n\n"
            "Example:\n"
            "from argo_cube import run_argo_query\n"
            "cube = run_argo_query(\n"
            "    start_date='1950-01-01',\n"
            f"    end_date='{DEFAULT_END_DATE}',\n"
            "    output='data/sojs_argo_monthly_density_1950_present.nc',\n"
            ")\n"
        )
        return 0

    args = parse_args(argv)
    run_argo_query(
        start_date=args.start_date,
        end_date=args.end_date,
        output=args.output,
        lon_min=args.lon_min,
        lon_max=args.lon_max,
        lat_min=args.lat_min,
        lat_max=args.lat_max,
        max_depth=args.max_depth,
        depth_step=args.depth_step,
        lat_step=args.lat_step,
        lon_step=args.lon_step,
        dataset=args.dataset,
        api_timeout=args.api_timeout,
        fetch_window_months=args.fetch_window_months,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
