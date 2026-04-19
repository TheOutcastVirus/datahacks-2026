from __future__ import annotations

import argparse
import warnings
from pathlib import Path
from typing import Sequence

warnings.filterwarnings(
    "ignore",
    message=r"Engine 'argo' loading failed:.*",
    category=RuntimeWarning,
)

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr


DEFAULT_INPUT = Path("data/sojs_argo_monthly_density_1950_present.nc")
DEFAULT_OUTPUT_DIR = Path("plots/argo")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create monthly visualizations for the Sojs Argo temperature, salinity, "
            "and density cube and save them as PNG files."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input NetCDF file. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory where plots will be written. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--shallow-max-depth",
        type=float,
        default=200.0,
        help="Maximum depth used for shallow-layer maps. Default: 200.",
    )
    parser.add_argument(
        "--recent-years",
        type=int,
        default=10,
        help="Number of trailing years used for recent-mean maps. Default: 10.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=160,
        help="Output DPI for saved figures. Default: 160.",
    )
    return parser.parse_args(argv)


def weighted_mean(
    data: xr.DataArray,
    weights: xr.DataArray,
    dims: tuple[str, ...],
) -> xr.DataArray:
    usable_weights = weights.where(np.isfinite(data) & np.isfinite(weights) & (weights > 0))
    weighted_sum = (data * usable_weights).sum(dim=dims, skipna=True)
    weight_sum = usable_weights.sum(dim=dims, skipna=True)
    return weighted_sum / weight_sum.where(weight_sum > 0)


def configure_matplotlib(dpi: int) -> None:
    plt.style.use("default")
    plt.rcParams.update(
        {
            "figure.dpi": dpi,
            "savefig.dpi": dpi,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "grid.alpha": 0.22,
        }
    )


def open_cube(input_path: Path) -> xr.Dataset:
    ds = xr.open_dataset(input_path, engine="netcdf4")
    required_vars = {"temperature", "salinity", "density", "sample_count"}
    missing_vars = required_vars.difference(ds.data_vars)
    if missing_vars:
        raise KeyError(
            f"Dataset is missing required variables: {', '.join(sorted(missing_vars))}"
        )
    return ds


def nonempty_time_slice(
    ds: xr.Dataset,
    recent_years: int,
) -> tuple[xr.Dataset, pd.Timestamp, pd.Timestamp]:
    supported_times = ds["time"].where(
        ds["sample_count"].sum(dim=("latitude", "longitude", "depth")) > 0,
        drop=True,
    )
    if supported_times.size == 0:
        raise ValueError("The input cube has no populated monthly cells.")

    last_supported = pd.Timestamp(supported_times.values[-1]).to_period("M").to_timestamp()
    window_start = (last_supported - pd.DateOffset(years=recent_years) + pd.offsets.MonthBegin(1))
    subset = ds.sel(time=slice(window_start, last_supported))
    return subset, window_start, last_supported


def quantile_limits(field: xr.DataArray, low: float = 0.02, high: float = 0.98) -> tuple[float, float]:
    values = np.asarray(field.values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return (0.0, 1.0)
    vmin = float(np.quantile(values, low))
    vmax = float(np.quantile(values, high))
    if np.isclose(vmin, vmax):
        vmax = vmin + 1.0
    return vmin, vmax


def save_support_timeseries(
    times: np.ndarray,
    support_cells: np.ndarray,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.8))
    support_series = pd.Series(support_cells, index=pd.to_datetime(times))
    rolling = support_series.rolling(12, min_periods=1).mean()

    ax.bar(
        support_series.index,
        support_series.values,
        width=25,
        color="#88a9bf",
        edgecolor="#345065",
        linewidth=0.35,
        label="Monthly supported cells",
    )
    ax.plot(
        rolling.index,
        rolling.values,
        color="#7a2e1f",
        linewidth=2.0,
        label="12-month mean",
    )
    ax.set_title("Monthly Argo Grid Support Through Time")
    ax.set_ylabel("Supported grid cells")
    ax.set_xlabel("Time")
    ax.xaxis.set_major_locator(mdates.YearLocator(base=5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def save_support_calendar_heatmap(
    times: np.ndarray,
    support_cells: np.ndarray,
    output_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(times),
            "support": support_cells,
        }
    )
    frame["year"] = frame["time"].dt.year
    frame["month"] = frame["time"].dt.month
    heatmap = frame.pivot(index="year", columns="month", values="support").sort_index()

    fig, ax = plt.subplots(figsize=(10, max(5, heatmap.shape[0] * 0.22)))
    mesh = ax.imshow(heatmap.values, aspect="auto", cmap="magma")
    ax.set_title("Monthly Argo Grid Support Calendar")
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")
    ax.set_xticks(np.arange(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])

    year_step = max(1, int(np.ceil(heatmap.shape[0] / 16)))
    y_positions = np.arange(0, heatmap.shape[0], year_step)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(heatmap.index.to_numpy()[y_positions])

    cbar = fig.colorbar(mesh, ax=ax, pad=0.02)
    cbar.set_label("Supported grid cells")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def save_depth_profile(
    depths: np.ndarray,
    values: np.ndarray,
    title: str,
    xlabel: str,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 7.2))
    ax.plot(values, depths, color="#7a3e00", linewidth=2)
    ax.fill_betweenx(depths, 0, values, color="#c97a2b", alpha=0.28)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Depth (dbar)")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def save_map(
    field: xr.DataArray,
    title: str,
    colorbar_label: str,
    output_path: Path,
    cmap: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 6.4))
    vmin, vmax = quantile_limits(field)
    mesh = ax.pcolormesh(
        field["longitude"].values,
        field["latitude"].values,
        field.values,
        shading="auto",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    colorbar = fig.colorbar(mesh, ax=ax, pad=0.02)
    colorbar.set_label(colorbar_label)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def save_time_depth_section(
    section: xr.DataArray,
    title: str,
    colorbar_label: str,
    output_path: Path,
    cmap: str,
) -> None:
    section_2d = section.transpose("depth", "time")
    fig, ax = plt.subplots(figsize=(11, 5.6))
    vmin, vmax = quantile_limits(section_2d)
    mesh = ax.pcolormesh(
        section_2d["time"].values,
        section_2d["depth"].values,
        section_2d.values,
        shading="auto",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_title(title)
    ax.set_xlabel("Time")
    ax.set_ylabel("Depth (dbar)")
    ax.invert_yaxis()
    ax.xaxis.set_major_locator(mdates.YearLocator(base=5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    colorbar = fig.colorbar(mesh, ax=ax, pad=0.02)
    colorbar.set_label(colorbar_label)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_matplotlib(args.dpi)

    if not args.input.exists():
        raise FileNotFoundError(f"Input NetCDF file not found: {args.input}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ds = open_cube(args.input)

    sample_count = ds["sample_count"].fillna(0)
    temperature = ds["temperature"]
    salinity = ds["salinity"]
    density = ds["density"]

    recent_ds, window_start, window_end = nonempty_time_slice(ds, args.recent_years)
    recent_count = recent_ds["sample_count"].fillna(0)

    shallow_recent_count = recent_count.sel(depth=slice(0, args.shallow_max_depth))
    shallow_recent_temperature = weighted_mean(
        recent_ds["temperature"].sel(depth=slice(0, args.shallow_max_depth)),
        shallow_recent_count,
        dims=("time", "depth"),
    )
    shallow_recent_salinity = weighted_mean(
        recent_ds["salinity"].sel(depth=slice(0, args.shallow_max_depth)),
        shallow_recent_count,
        dims=("time", "depth"),
    )
    shallow_recent_density = weighted_mean(
        recent_ds["density"].sel(depth=slice(0, args.shallow_max_depth)),
        shallow_recent_count,
        dims=("time", "depth"),
    )
    shallow_recent_support = shallow_recent_count.sum(dim=("time", "depth"), skipna=True)

    temperature_section = weighted_mean(
        temperature,
        sample_count,
        dims=("latitude", "longitude"),
    )
    salinity_section = weighted_mean(
        salinity,
        sample_count,
        dims=("latitude", "longitude"),
    )
    density_section = weighted_mean(
        density,
        sample_count,
        dims=("latitude", "longitude"),
    )

    valid_cells_by_time = (sample_count > 0).sum(
        dim=("latitude", "longitude", "depth")
    ).values
    support_by_depth = sample_count.sum(dim=("time", "latitude", "longitude")).values

    save_support_timeseries(
        ds["time"].values,
        valid_cells_by_time,
        args.output_dir / "monthly_cells_with_support.png",
    )
    save_support_timeseries(
        ds["time"].values,
        valid_cells_by_time,
        args.output_dir / "cells_with_support_by_time.png",
    )
    save_support_calendar_heatmap(
        ds["time"].values,
        valid_cells_by_time,
        args.output_dir / "monthly_support_calendar_heatmap.png",
    )
    save_depth_profile(
        ds["depth"].values,
        support_by_depth,
        "Total Sample Support By Depth",
        "Summed sample_count",
        args.output_dir / "sample_support_by_depth.png",
    )
    save_map(
        shallow_recent_support,
        (
            f"Shallow Sample Support, {window_start.year}-{window_end.year} "
            f"(0-{int(args.shallow_max_depth)} dbar)"
        ),
        "Summed sample_count",
        args.output_dir / "shallow_sample_support_map.png",
        cmap="magma",
    )
    save_map(
        shallow_recent_temperature,
        (
            f"Recent Mean Temperature, {window_start.year}-{window_end.year} "
            f"(0-{int(args.shallow_max_depth)} dbar)"
        ),
        "Temperature (deg C)",
        args.output_dir / "shallow_temperature_map.png",
        cmap="coolwarm",
    )
    save_map(
        shallow_recent_salinity,
        (
            f"Recent Mean Salinity, {window_start.year}-{window_end.year} "
            f"(0-{int(args.shallow_max_depth)} dbar)"
        ),
        "Salinity",
        args.output_dir / "shallow_salinity_map.png",
        cmap="viridis",
    )
    save_map(
        shallow_recent_density,
        (
            f"Recent Mean Density, {window_start.year}-{window_end.year} "
            f"(0-{int(args.shallow_max_depth)} dbar)"
        ),
        "Density (kg m-3)",
        args.output_dir / "shallow_density_map.png",
        cmap="cividis",
    )
    save_time_depth_section(
        temperature_section,
        "Temperature Time-Depth Section",
        "Temperature (deg C)",
        args.output_dir / "temperature_time_depth.png",
        cmap="coolwarm",
    )
    save_time_depth_section(
        salinity_section,
        "Salinity Time-Depth Section",
        "Salinity",
        args.output_dir / "salinity_time_depth.png",
        cmap="viridis",
    )
    save_time_depth_section(
        density_section,
        "Density Time-Depth Section",
        "Density (kg m-3)",
        args.output_dir / "density_time_depth.png",
        cmap="cividis",
    )

    print(f"Saved plots to {args.output_dir.resolve()}")
    for path in sorted(args.output_dir.glob("*.png")):
        print(f" - {path.name}")

    ds.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
