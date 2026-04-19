"""Explore calcofi_temp_salinity.nc and produce preliminary plots."""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from project_paths import PLOTS_DIR, PROCESSED_CALCOFI_NC


NC = PROCESSED_CALCOFI_NC
OUT = PLOTS_DIR
OUT.mkdir(parents=True, exist_ok=True)


def load_dataset(path: Path) -> xr.Dataset:
    if not path.exists():
        raise FileNotFoundError(
            f"NetCDF file not found: {path}. Run build_nc.py first."
        )
    if path.stat().st_size == 0:
        raise ValueError(
            f"{path} is 0 bytes, so it is not a valid NetCDF file. "
            "A previous write likely failed because the file was locked. "
            "Close any notebook/viewer using it, rebuild with build_nc.py, and try again."
        )

    try:
        with xr.open_dataset(path, engine="netcdf4") as opened:
            return opened.load()
    except OSError as exc:
        raise OSError(
            f"Failed to open {path} as NetCDF4. The file may be corrupt or partially written. "
            "Rebuild it with build_nc.py after closing any process that has it open."
        ) from exc


def describe(ds: xr.Dataset) -> None:
    print("=== Dataset ===")
    print(ds)
    print("\n=== Dims ===", dict(ds.sizes))
    print("\n=== Coord ranges ===")
    print(f"time : {ds.time.min().values} -> {ds.time.max().values}")
    print(f"lat  : {float(ds.lat.min()):.3f} -> {float(ds.lat.max()):.3f}")
    print(f"lon  : {float(ds.lon.min()):.3f} -> {float(ds.lon.max()):.3f}")
    print(f"depth: {float(ds.depth.min()):.1f} -> {float(ds.depth.max()):.1f} m")
    for v in ("Temp", "Salinity"):
        da = ds[v]
        print(
            f"{v}: n={int(da.count())}, min={float(da.min()):.3f}, "
            f"mean={float(da.mean()):.3f}, max={float(da.max()):.3f}"
        )


def plot_station_map(ds: xr.Dataset) -> None:
    years = pd.to_datetime(ds.time.values).year
    fig, ax = plt.subplots(figsize=(7, 6))
    sc = ax.scatter(ds.lon, ds.lat, c=years, s=2, cmap="viridis")
    la_jolla_lon = -117.2714
    la_jolla_lat = 32.8506
    ax.scatter(
        la_jolla_lon,
        la_jolla_lat,
        s=36,
        color="crimson",
        edgecolor="white",
        linewidth=0.8,
        zorder=3,
    )
    ax.annotate(
        "La Jolla",
        xy=(la_jolla_lon, la_jolla_lat),
        xytext=(8, 6),
        textcoords="offset points",
        color="crimson",
        fontsize=9,
        fontweight="bold",
        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.8},
    )
    ax.set(xlabel="Longitude", ylabel="Latitude", title="CalCOFI station locations")
    plt.colorbar(sc, ax=ax, label="Year")
    fig.tight_layout()
    fig.savefig(OUT / "stations.png", dpi=130)
    plt.close(fig)


def _smooth_monthly_segments(
    series: pd.Series, window: int = 5, min_periods: int = 2
) -> pd.Series:
    """Smooth contiguous monthly runs without bridging missing-data gaps."""
    smoothed = pd.Series(np.nan, index=series.index, dtype=float)
    valid = series.notna()
    if not valid.any():
        return smoothed

    segment_ids = valid.ne(valid.shift(fill_value=False)).cumsum()
    for _, segment in series[valid].groupby(segment_ids[valid]):
        smoothed.loc[segment.index] = segment.rolling(
            window=window,
            center=True,
            min_periods=min_periods,
        ).mean()

    return smoothed


def plot_surface_timeseries(ds: xr.Dataset, surface_m: float = 10.0) -> None:
    """Mean over top `surface_m` meters, resampled monthly, with gaps preserved."""
    surf = ds.sel(depth=slice(0, surface_m)).mean(dim="depth", skipna=True)
    df = (
        pd.DataFrame(
            {
                "time": pd.to_datetime(ds.time.values),
                "Temp": surf.Temp.values,
                "Salinity": surf.Salinity.values,
            }
        )
        .dropna(subset=["Temp", "Salinity"], how="all")
        .set_index("time")
        .sort_index()
    )

    monthly = df.resample("MS").mean()
    # Break lines across multi-month sampling gaps before smoothing.
    gap = monthly.index.to_series().diff().dt.days > 70
    monthly.loc[gap] = np.nan
    latest_time = monthly.index.max()
    window_start = latest_time - pd.DateOffset(years=20)
    monthly = monthly.loc[monthly.index >= window_start]

    temp_smooth = _smooth_monthly_segments(monthly["Temp"])
    salinity_smooth = _smooth_monthly_segments(monthly["Salinity"])

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(monthly.index, monthly["Temp"], color="tab:red", lw=0.8, alpha=0.25)
    axes[0].plot(monthly.index, temp_smooth, color="tab:red", lw=1.8)
    axes[0].set_ylabel("Temp (deg C)")
    axes[0].set_title(f"Surface (<= {surface_m:.0f} m) monthly mean")

    axes[1].plot(
        monthly.index,
        monthly["Salinity"],
        color="tab:blue",
        lw=0.8,
        alpha=0.25,
    )
    axes[1].plot(monthly.index, salinity_smooth, color="tab:blue", lw=1.8)
    axes[1].set_ylabel("Salinity (PSU)")

    fig.tight_layout()
    fig.savefig(OUT / "surface_timeseries.png", dpi=130)
    plt.close(fig)


def plot_depth_profiles(ds: xr.Dataset) -> None:
    t_prof = ds.Temp.mean(dim="profile", skipna=True)
    s_prof = ds.Salinity.mean(dim="profile", skipna=True)
    fig, axes = plt.subplots(1, 2, figsize=(9, 6), sharey=True)
    axes[0].plot(t_prof, ds.depth, color="tab:red")
    axes[0].set(xlabel="Temp (deg C)", ylabel="Depth (m)", title="Mean T profile")
    axes[0].invert_yaxis()
    axes[1].plot(s_prof, ds.depth, color="tab:blue")
    axes[1].set(xlabel="Salinity (PSU)", title="Mean S profile")
    fig.tight_layout()
    fig.savefig(OUT / "depth_profiles.png", dpi=130)
    plt.close(fig)


def plot_ts_diagram(ds: xr.Dataset) -> None:
    t = ds.Temp.values.ravel()
    s = ds.Salinity.values.ravel()
    m = np.isfinite(t) & np.isfinite(s)
    if m.sum() > 200_000:
        idx = np.random.default_rng(0).choice(np.flatnonzero(m), 200_000, replace=False)
    else:
        idx = np.flatnonzero(m)
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.hexbin(s[idx], t[idx], gridsize=80, mincnt=1, cmap="magma", bins="log")
    ax.set(xlabel="Salinity (PSU)", ylabel="Temp (deg C)", title="T-S diagram")
    fig.tight_layout()
    fig.savefig(OUT / "ts_diagram.png", dpi=130)
    plt.close(fig)


def main() -> None:
    ds = load_dataset(NC)
    describe(ds)
    plot_station_map(ds)
    plot_surface_timeseries(ds)
    plot_depth_profiles(ds)
    plot_ts_diagram(ds)
    print(f"\nPlots written to {OUT}")


if __name__ == "__main__":
    main()
