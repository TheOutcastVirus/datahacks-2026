from __future__ import annotations

import argparse
from dataclasses import dataclass
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


DEFAULT_OUTPUT_DIR = Path("data/normalized")
DEFAULT_PLOT_DIR = Path("plots/normalized")
DEFAULT_GOM_MIN_LON = -72.0
DEFAULT_GOM_MAX_LON = -64.0
DEFAULT_GOM_MIN_LAT = 41.0
DEFAULT_GOM_MAX_LAT = 48.0
DEFAULT_ARGO_MIN_LON = -80.0
DEFAULT_ARGO_MAX_LON = -55.0
DEFAULT_ARGO_MIN_LAT = 38.0
DEFAULT_ARGO_MAX_LAT = 48.0
DEFAULT_ARGO_MAX_DEPTH = 200.0
DEFAULT_ARGO_MIN_SUPPORT = 18
DEFAULT_ARGO_MIN_CELLS = 2

COOPS_PATHS = {
    "rockland_msl_m": Path("data/coops/rockland_8415490_monthly_mean_msl.nc"),
    "portland_msl_m": Path("data/coops/portland_8418150_monthly_mean_msl.nc"),
    "bar_harbor_msl_m": Path("data/coops/bar_harbor_8413320_monthly_mean_msl.nc"),
}
COPERNICUS_PATH = Path("data/copernicusmarine/gulf_of_maine_sla.nc")
GRACE_HIST_PATH = Path("data/grace_grac_ocn/grace_ocean_mass_2002_2017.nc")
GREENLAND_PATH = Path("data/greenland_mass/greenland_mass_timeseries.nc")
ARGO_PATH = Path("data/sojs_argo_monthly_density_1950_present.nc")


@dataclass(frozen=True)
class SeriesSpec:
    name: str
    role: str
    units: str
    source: str
    family: str
    notes: str


SERIES_SPECS = {
    "rockland_msl_m": SeriesSpec(
        name="rockland_msl_m",
        role="model_input",
        units="m",
        source="NOAA CO-OPS",
        family="coops",
        notes="Monthly mean sea level at Rockland.",
    ),
    "portland_msl_m": SeriesSpec(
        name="portland_msl_m",
        role="model_input",
        units="m",
        source="NOAA CO-OPS",
        family="coops",
        notes="Monthly mean sea level at Portland.",
    ),
    "bar_harbor_msl_m": SeriesSpec(
        name="bar_harbor_msl_m",
        role="model_input",
        units="m",
        source="NOAA CO-OPS",
        family="coops",
        notes="Monthly mean sea level at Bar Harbor.",
    ),
    "copernicus_sla_gom_m": SeriesSpec(
        name="copernicus_sla_gom_m",
        role="model_input",
        units="m",
        source="Copernicus Marine",
        family="copernicusmarine",
        notes="Area-mean Gulf of Maine sea level anomaly.",
    ),
    "copernicus_adt_gom_m": SeriesSpec(
        name="copernicus_adt_gom_m",
        role="reference_context",
        units="m",
        source="Copernicus Marine",
        family="copernicusmarine",
        notes="Area-mean Gulf of Maine absolute dynamic topography.",
    ),
    "grace_hist_lwe_thickness_gom_m": SeriesSpec(
        name="grace_hist_lwe_thickness_gom_m",
        role="reference_context",
        units="m",
        source="NASA PO.DAAC GRACE",
        family="grace_hist",
        notes="Area-mean Gulf of Maine liquid-water-equivalent thickness anomaly.",
    ),
    "grace_hist_uncertainty_gom_m": SeriesSpec(
        name="grace_hist_uncertainty_gom_m",
        role="diagnostic_only",
        units="m",
        source="NASA PO.DAAC GRACE",
        family="grace_hist",
        notes="Area-mean Gulf of Maine GRACE uncertainty.",
    ),
    "greenland_mass_gt": SeriesSpec(
        name="greenland_mass_gt",
        role="reference_context",
        units="Gt",
        source="NASA PO.DAAC Greenland Mass",
        family="greenland_mass",
        notes="Greenland whole-ice-sheet mass anomaly.",
    ),
    "greenland_mass_sigma_gt": SeriesSpec(
        name="greenland_mass_sigma_gt",
        role="diagnostic_only",
        units="Gt",
        source="NASA PO.DAAC Greenland Mass",
        family="greenland_mass",
        notes="Greenland whole-ice-sheet 1-sigma mass uncertainty.",
    ),
    "argo_temperature_shelf_0_200dbar_deg_c": SeriesSpec(
        name="argo_temperature_shelf_0_200dbar_deg_c",
        role="model_input",
        units="degree_Celsius",
        source="Argo ERDDAP",
        family="argo",
        notes=(
            "Sample-count-weighted monthly mean Argo temperature over the NW Atlantic "
            "shelf regional context, 0-200 dbar."
        ),
    ),
    "argo_salinity_shelf_0_200dbar": SeriesSpec(
        name="argo_salinity_shelf_0_200dbar",
        role="model_input",
        units="1",
        source="Argo ERDDAP",
        family="argo",
        notes=(
            "Sample-count-weighted monthly mean Argo practical salinity over the NW "
            "Atlantic shelf regional context, 0-200 dbar."
        ),
    ),
    "argo_density_shelf_0_200dbar_kg_m3": SeriesSpec(
        name="argo_density_shelf_0_200dbar_kg_m3",
        role="model_input",
        units="kg m-3",
        source="Argo ERDDAP",
        family="argo",
        notes=(
            "Sample-count-weighted monthly mean Argo in-situ density over the NW "
            "Atlantic shelf regional context, 0-200 dbar."
        ),
    ),
    "argo_sample_count_shelf_0_200dbar": SeriesSpec(
        name="argo_sample_count_shelf_0_200dbar",
        role="diagnostic_only",
        units="count",
        source="Argo ERDDAP",
        family="argo",
        notes=(
            "Summed monthly Argo sample_count over the retained NW Atlantic shelf "
            "regional context, 0-200 dbar."
        ),
    ),
    "argo_grid_cells_shelf_0_200dbar": SeriesSpec(
        name="argo_grid_cells_shelf_0_200dbar",
        role="diagnostic_only",
        units="count",
        source="Argo ERDDAP",
        family="argo",
        notes=(
            "Number of lat/lon grid cells with any retained Argo shallow support in the "
            "NW Atlantic shelf regional context."
        ),
    ),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize the active Sojs datasets onto a shared monthly timeline, "
            "save reconciled NetCDF outputs, and generate coverage diagnostics."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--gom-min-lon", type=float, default=DEFAULT_GOM_MIN_LON)
    parser.add_argument("--gom-max-lon", type=float, default=DEFAULT_GOM_MAX_LON)
    parser.add_argument("--gom-min-lat", type=float, default=DEFAULT_GOM_MIN_LAT)
    parser.add_argument("--gom-max-lat", type=float, default=DEFAULT_GOM_MAX_LAT)
    parser.add_argument("--argo-min-lon", type=float, default=DEFAULT_ARGO_MIN_LON)
    parser.add_argument("--argo-max-lon", type=float, default=DEFAULT_ARGO_MAX_LON)
    parser.add_argument("--argo-min-lat", type=float, default=DEFAULT_ARGO_MIN_LAT)
    parser.add_argument("--argo-max-lat", type=float, default=DEFAULT_ARGO_MAX_LAT)
    parser.add_argument("--argo-max-depth", type=float, default=DEFAULT_ARGO_MAX_DEPTH)
    parser.add_argument("--argo-min-support", type=int, default=DEFAULT_ARGO_MIN_SUPPORT)
    parser.add_argument("--argo-min-cells", type=int, default=DEFAULT_ARGO_MIN_CELLS)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.gom_min_lon >= args.gom_max_lon:
        raise SystemExit("--gom-min-lon must be smaller than --gom-max-lon.")
    if args.gom_min_lat >= args.gom_max_lat:
        raise SystemExit("--gom-min-lat must be smaller than --gom-max-lat.")
    if args.argo_min_lon >= args.argo_max_lon:
        raise SystemExit("--argo-min-lon must be smaller than --argo-max-lon.")
    if args.argo_min_lat >= args.argo_max_lat:
        raise SystemExit("--argo-min-lat must be smaller than --argo-max-lat.")
    if args.argo_max_depth <= 0:
        raise SystemExit("--argo-max-depth must be positive.")
    if args.argo_min_support <= 0:
        raise SystemExit("--argo-min-support must be positive.")
    if args.argo_min_cells <= 0:
        raise SystemExit("--argo-min-cells must be positive.")


def choose_coord_name(ds: xr.Dataset, candidates: list[str]) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(f"Could not find any coordinate among {candidates}.")


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


def monthly_series_from_data_array(data_array: xr.DataArray) -> pd.Series:
    index = pd.to_datetime(data_array["time"].values)
    series = pd.Series(data_array.values, index=index)
    series = series.groupby(series.index).mean().sort_index()
    return series.resample("MS").mean()


def weighted_mean_with_sample_count(
    data_array: xr.DataArray,
    sample_count: xr.DataArray,
    dims: tuple[str, ...],
) -> xr.DataArray:
    usable_weights = sample_count.where(
        np.isfinite(data_array) & np.isfinite(sample_count) & (sample_count > 0)
    )
    weighted_sum = (data_array * usable_weights).sum(dim=dims, skipna=True)
    weight_sum = usable_weights.sum(dim=dims, skipna=True)
    return weighted_sum / weight_sum.where(weight_sum > 0)


def load_coops_series(path: Path, variable_name: str) -> pd.Series:
    ds = xr.open_dataset(path)
    try:
        series = monthly_series_from_data_array(ds["msl"])
    finally:
        ds.close()
    series.name = variable_name
    return series


def load_copernicus_series(
    path: Path,
    *,
    variable_name: str,
    output_name: str,
) -> pd.Series:
    ds = xr.open_dataset(path)
    try:
        lat_name = choose_coord_name(ds, ["latitude", "lat", "y"])
        lon_name = choose_coord_name(ds, ["longitude", "lon", "x"])
        series = weighted_area_mean(ds[variable_name], lat_name, lon_name)
        monthly = monthly_series_from_data_array(series)
    finally:
        ds.close()
    monthly.name = output_name
    return monthly


def load_grace_series(
    path: Path,
    *,
    variable_name: str,
    output_name: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> pd.Series:
    ds = xr.open_dataset(path)
    try:
        lat_name = choose_coord_name(ds, ["lat", "latitude", "y"])
        lon_name = choose_coord_name(ds, ["lon", "longitude", "x"])
        regional = subset_bbox(
            ds[variable_name],
            lat_name=lat_name,
            lon_name=lon_name,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        series = weighted_area_mean(regional, lat_name, lon_name)
        monthly = monthly_series_from_data_array(series)
    finally:
        ds.close()
    monthly.name = output_name
    return monthly


def load_greenland_series(path: Path, variable_name: str) -> pd.Series:
    ds = xr.open_dataset(path)
    try:
        monthly = monthly_series_from_data_array(ds[variable_name])
    finally:
        ds.close()
    monthly.name = variable_name
    return monthly


def load_argo_series(args: argparse.Namespace) -> list[pd.Series]:
    ds = xr.open_dataset(ARGO_PATH)
    try:
        regional = ds.sel(
            latitude=slice(args.argo_min_lat, args.argo_max_lat),
            longitude=slice(args.argo_min_lon, args.argo_max_lon),
            depth=slice(0, args.argo_max_depth),
        )
        sample_count = regional["sample_count"].fillna(0)
        support = sample_count.sum(dim=("latitude", "longitude", "depth"), skipna=True)
        grid_cells = (sample_count.sum(dim="depth", skipna=True) > 0).sum(
            dim=("latitude", "longitude")
        )
        valid_month_mask = (
            (support >= args.argo_min_support)
            & (grid_cells >= args.argo_min_cells)
        )

        temperature = weighted_mean_with_sample_count(
            regional["temperature"],
            sample_count,
            dims=("latitude", "longitude", "depth"),
        ).where(valid_month_mask)
        salinity = weighted_mean_with_sample_count(
            regional["salinity"],
            sample_count,
            dims=("latitude", "longitude", "depth"),
        ).where(valid_month_mask)
        density = weighted_mean_with_sample_count(
            regional["density"],
            sample_count,
            dims=("latitude", "longitude", "depth"),
        ).where(valid_month_mask)
        support = support.where(valid_month_mask)
        grid_cells = grid_cells.where(valid_month_mask)
    finally:
        ds.close()

    outputs = [
        monthly_series_from_data_array(temperature),
        monthly_series_from_data_array(salinity),
        monthly_series_from_data_array(density),
        monthly_series_from_data_array(support),
        monthly_series_from_data_array(grid_cells),
    ]
    outputs[0].name = "argo_temperature_shelf_0_200dbar_deg_c"
    outputs[1].name = "argo_salinity_shelf_0_200dbar"
    outputs[2].name = "argo_density_shelf_0_200dbar_kg_m3"
    outputs[3].name = "argo_sample_count_shelf_0_200dbar"
    outputs[4].name = "argo_grid_cells_shelf_0_200dbar"
    return outputs


def build_raw_frame(args: argparse.Namespace) -> pd.DataFrame:
    series_list: list[pd.Series] = []
    for name, path in COOPS_PATHS.items():
        series_list.append(load_coops_series(path, name))
    series_list.append(
        load_copernicus_series(
            COPERNICUS_PATH,
            variable_name="sla",
            output_name="copernicus_sla_gom_m",
        )
    )
    series_list.append(
        load_copernicus_series(
            COPERNICUS_PATH,
            variable_name="adt",
            output_name="copernicus_adt_gom_m",
        )
    )
    series_list.append(
        load_grace_series(
            GRACE_HIST_PATH,
            variable_name="lwe_thickness",
            output_name="grace_hist_lwe_thickness_gom_m",
            min_lat=args.gom_min_lat,
            max_lat=args.gom_max_lat,
            min_lon=args.gom_min_lon,
            max_lon=args.gom_max_lon,
        )
    )
    series_list.append(
        load_grace_series(
            GRACE_HIST_PATH,
            variable_name="uncertainty",
            output_name="grace_hist_uncertainty_gom_m",
            min_lat=args.gom_min_lat,
            max_lat=args.gom_max_lat,
            min_lon=args.gom_min_lon,
            max_lon=args.gom_max_lon,
        )
    )
    series_list.append(load_greenland_series(GREENLAND_PATH, "greenland_mass_gt"))
    series_list.append(load_greenland_series(GREENLAND_PATH, "greenland_mass_sigma_gt"))
    series_list.extend(load_argo_series(args))

    start = min(series.dropna().index.min() for series in series_list)
    end = max(series.dropna().index.max() for series in series_list)
    monthly_index = pd.date_range(start=start, end=end, freq="MS")
    frame = pd.DataFrame(index=monthly_index)
    for series in series_list:
        frame[series.name] = series.reindex(monthly_index)
    frame.index.name = "time"
    return frame


def add_normalized_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in frame.columns:
        valid = frame[column].dropna()
        mean = float(valid.mean()) if not valid.empty else np.nan
        std = float(valid.std(ddof=0)) if len(valid) > 1 else np.nan
        normalized[f"{column}_anomaly"] = frame[column] - mean
        normalized[f"{column}_zscore"] = (
            (frame[column] - mean) / std if std and not np.isnan(std) else np.nan
        )
    return normalized


def build_dataset(
    frame: pd.DataFrame,
    *,
    modern_overlap_index: pd.DatetimeIndex,
    argo_overlap_index: pd.DatetimeIndex,
    argo_cleaning_description: str,
) -> xr.Dataset:
    ds = xr.Dataset(coords={"time": frame.index.to_numpy(dtype="datetime64[ns]")})
    ds["is_modern_overlap_month"] = ("time", frame.index.isin(modern_overlap_index).astype(np.int8))
    ds["is_modern_overlap_month"].attrs.update(
        {
            "long_name": "Indicator for months in the modern full-overlap subset",
            "flag_values": [0, 1],
            "flag_meanings": "outside_overlap inside_overlap",
        }
    )
    ds["is_argo_overlap_month"] = ("time", frame.index.isin(argo_overlap_index).astype(np.int8))
    ds["is_argo_overlap_month"].attrs.update(
        {
            "long_name": "Indicator for months in the overlap subset that also retains cleaned Argo series",
            "flag_values": [0, 1],
            "flag_meanings": "outside_overlap inside_overlap",
        }
    )

    for column in frame.columns:
        ds[column] = ("time", frame[column].to_numpy(dtype=float))
        if column.endswith("_anomaly"):
            base_name = column[: -len("_anomaly")]
            spec = SERIES_SPECS[base_name]
            ds[column].attrs.update(
                {
                    "units": spec.units,
                    "normalization": "mean_centered",
                    "derived_from": base_name,
                    "source": spec.source,
                    "role": spec.role,
                }
            )
        elif column.endswith("_zscore"):
            base_name = column[: -len("_zscore")]
            spec = SERIES_SPECS[base_name]
            ds[column].attrs.update(
                {
                    "units": "standard_deviation",
                    "normalization": "zscore",
                    "derived_from": base_name,
                    "source": spec.source,
                    "role": spec.role,
                }
            )
        else:
            spec = SERIES_SPECS[column]
            ds[column].attrs.update(
                {
                    "units": spec.units,
                    "source": spec.source,
                    "role": spec.role,
                    "family": spec.family,
                    "notes": spec.notes,
                }
            )

    ds.attrs.update(
        {
            "title": "Sojs active monthly normalized dataset",
            "description": (
                "Monthly aligned Sojs data stack built from retained CO-OPS, "
                "Copernicus Marine, historical GRACE, Greenland mass, and cleaned "
                "Argo shelf-context sources."
            ),
            "normalization": (
                "Union monthly time base with per-series mean-centered anomalies and z-scores."
            ),
            "modern_overlap_definition": (
                "Months where all retained modern-era variables are present: "
                "Portland, Bar Harbor, Copernicus SLA/ADT, historical GRACE, and Greenland mass."
            ),
            "argo_overlap_definition": (
                "Months where the modern-era retained variables are present and the cleaned "
                "Argo shelf-context temperature, salinity, and density series also pass the "
                "minimum support filters."
            ),
            "excluded_from_modern_overlap": "rockland_msl_m",
            "argo_cleaning": argo_cleaning_description,
        }
    )
    return ds


def build_overlap_dataset(frame: pd.DataFrame, *, title: str, description: str) -> xr.Dataset:
    overlap = frame.copy()
    ds = xr.Dataset(coords={"time": overlap.index.to_numpy(dtype="datetime64[ns]")})
    for column in overlap.columns:
        ds[column] = ("time", overlap[column].to_numpy(dtype=float))
        source_column = column
        if column.endswith("_anomaly"):
            source_column = column[: -len("_anomaly")]
        elif column.endswith("_zscore"):
            source_column = column[: -len("_zscore")]
        ds[column].attrs.update({"derived_from": source_column})
    ds.attrs.update(
        {
            "title": title,
            "description": description,
            "excluded_variable": "rockland_msl_m",
        }
    )
    return ds


def save_dataset(ds: xr.Dataset, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding: dict[str, dict[str, object]] = {}
    for variable_name in ds.data_vars:
        data_array = ds[variable_name]
        if np.issubdtype(data_array.dtype, np.floating):
            encoding[variable_name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
        else:
            encoding[variable_name] = {"zlib": True, "complevel": 4}
    ds.to_netcdf(path, encoding=encoding)
    return path


def build_summary(frame: pd.DataFrame, modern_overlap_index: pd.DatetimeIndex) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for column, spec in SERIES_SPECS.items():
        valid = frame[column].dropna()
        modern_valid = frame.loc[modern_overlap_index, column].dropna()
        rows.append(
            {
                "variable": column,
                "role": spec.role,
                "family": spec.family,
                "source": spec.source,
                "units": spec.units,
                "time_start": valid.index.min().strftime("%Y-%m-%d") if not valid.empty else "",
                "time_end": valid.index.max().strftime("%Y-%m-%d") if not valid.empty else "",
                "available_months": int(valid.shape[0]),
                "missing_months_on_union_grid": int(frame[column].isna().sum()),
                "modern_overlap_months": int(modern_valid.shape[0]),
                "mean": float(valid.mean()) if not valid.empty else np.nan,
                "std": float(valid.std(ddof=0)) if len(valid) > 1 else np.nan,
            }
        )
    summary = pd.DataFrame(rows)
    summary[["mean", "std"]] = summary[["mean", "std"]].round(6)
    return summary


def build_overlap_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    columns = list(SERIES_SPECS)
    matrix = pd.DataFrame(index=columns, columns=columns, dtype=int)
    for left in columns:
        for right in columns:
            matrix.loc[left, right] = int(frame[[left, right]].dropna().shape[0])
    return matrix


def save_coverage_plot(frame: pd.DataFrame, path: Path) -> Path:
    data_columns = list(SERIES_SPECS)
    coverage = frame[data_columns].notna().astype(int).T
    fig, ax = plt.subplots(figsize=(16, 6))
    image = ax.imshow(coverage.values, aspect="auto", interpolation="nearest", cmap="Greys")
    ax.set_title("Sojs active data coverage on the union monthly timeline")
    ax.set_xlabel("Time")
    ax.set_ylabel("Variable")
    ax.set_yticks(np.arange(len(coverage.index)))
    ax.set_yticklabels(coverage.index)
    tick_positions = np.linspace(0, len(coverage.columns) - 1, num=min(10, len(coverage.columns)), dtype=int)
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([coverage.columns[idx].strftime("%Y-%m") for idx in tick_positions], rotation=45, ha="right")
    fig.colorbar(image, ax=ax, label="Coverage (1 = present)")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_modern_zscore_plot(frame: pd.DataFrame, modern_overlap_index: pd.DatetimeIndex, path: Path) -> Path:
    zscore_columns = [f"{column}_zscore" for column in SERIES_SPECS]
    overlap = frame.loc[modern_overlap_index, zscore_columns]
    fig, ax = plt.subplots(figsize=(13, 6))
    for column in zscore_columns:
        if overlap[column].notna().any():
            ax.plot(overlap.index, overlap[column], linewidth=1.3, label=column.replace("_zscore", ""))
    ax.set_title("Sojs normalized active-series comparison on the modern overlap window")
    ax.set_xlabel("Time")
    ax.set_ylabel("Z-score")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def save_tide_gauge_plot(frame: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(13, 6))
    for column in ["rockland_msl_m", "portland_msl_m", "bar_harbor_msl_m"]:
        ax.plot(frame.index, frame[column], linewidth=1.2, label=column.replace("_msl_m", ""))
    ax.set_title("Sojs retained tide-gauge monthly means on the union timeline")
    ax.set_xlabel("Time")
    ax.set_ylabel("MSL (m)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)

    raw_frame = build_raw_frame(args)
    normalized_frame = add_normalized_columns(raw_frame)

    modern_columns = [
        "portland_msl_m",
        "bar_harbor_msl_m",
        "copernicus_sla_gom_m",
        "copernicus_adt_gom_m",
        "grace_hist_lwe_thickness_gom_m",
        "grace_hist_uncertainty_gom_m",
        "greenland_mass_gt",
        "greenland_mass_sigma_gt",
    ]
    argo_columns = [
        "argo_temperature_shelf_0_200dbar_deg_c",
        "argo_salinity_shelf_0_200dbar",
        "argo_density_shelf_0_200dbar_kg_m3",
    ]
    modern_overlap_index = normalized_frame[modern_columns].dropna().index
    if modern_overlap_index.empty:
        raise SystemExit(
            "No modern overlap months were found across the retained modern-era variables."
        )
    argo_overlap_index = normalized_frame[modern_columns + argo_columns].dropna().index
    argo_cleaning_description = (
        "Argo monthly context series are masked unless sample_count >= "
        f"{args.argo_min_support} and occupied lat/lon grid cells >= "
        f"{args.argo_min_cells} within longitude {args.argo_min_lon} to {args.argo_max_lon}, "
        f"latitude {args.argo_min_lat} to {args.argo_max_lat}, and 0-{args.argo_max_depth} dbar."
    )

    dataset = build_dataset(
        normalized_frame,
        modern_overlap_index=modern_overlap_index,
        argo_overlap_index=argo_overlap_index,
        argo_cleaning_description=argo_cleaning_description,
    )
    overlap_dataset = build_overlap_dataset(
        normalized_frame.loc[modern_overlap_index],
        title="Sojs active modern overlap dataset",
        description=(
            "Monthly subset where the retained modern-era non-Argo variables are "
            "simultaneously available."
        ),
    )
    argo_overlap_dataset = build_overlap_dataset(
        normalized_frame.loc[argo_overlap_index],
        title="Sojs active modern overlap dataset with cleaned Argo context",
        description=(
            "Monthly subset where the retained modern-era variables and the cleaned Argo "
            "shelf-context temperature, salinity, and density series are simultaneously available."
        ),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.plot_dir.mkdir(parents=True, exist_ok=True)

    save_dataset(dataset, args.output_dir / "sojs_active_monthly_normalized.nc")
    save_dataset(overlap_dataset, args.output_dir / "sojs_active_modern_overlap.nc")
    save_dataset(argo_overlap_dataset, args.output_dir / "sojs_active_modern_overlap_with_argo.nc")

    summary = build_summary(raw_frame, modern_overlap_index)
    summary.to_csv(args.plot_dir / "sojs_active_normalization_summary.csv", index=False)

    overlap_matrix = build_overlap_matrix(raw_frame)
    overlap_matrix.to_csv(args.plot_dir / "sojs_active_overlap_matrix.csv")

    save_coverage_plot(raw_frame, args.plot_dir / "sojs_active_coverage.png")
    save_modern_zscore_plot(
        normalized_frame,
        modern_overlap_index,
        args.plot_dir / "sojs_active_modern_overlap_zscores.png",
    )
    save_tide_gauge_plot(raw_frame, args.plot_dir / "sojs_retained_tide_gauges.png")

    dataset.close()
    overlap_dataset.close()
    argo_overlap_dataset.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
