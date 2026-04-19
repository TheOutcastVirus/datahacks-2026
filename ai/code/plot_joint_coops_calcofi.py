"""Plot joint La Jolla sea level and nearby CalCOFI temperature/salinity views."""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from project_paths import PLOTS_DIR, PROCESSED_CALCOFI_NC, PROCESSED_COOPS_NC


LA_JOLLA_LAT = 32.867
LA_JOLLA_LON = -117.257
LOCAL_RADIUS_DEG = 1.5
SURFACE_M = 10.0


SEA_NC = PROCESSED_COOPS_NC
CALCOFI_NC = PROCESSED_CALCOFI_NC
OUT = PLOTS_DIR
OUT.mkdir(parents=True, exist_ok=True)


def _smooth_monthly_segments(
    series: pd.Series, window: int = 12, min_periods: int = 6
) -> pd.Series:
    """Smooth contiguous monthly runs without bridging across missing gaps."""
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


def _monthly_anomaly(series: pd.Series) -> pd.Series:
    climatology = series.groupby(series.index.month).transform("mean")
    return series - climatology


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(skipna=True)
    if std == 0 or pd.isna(std):
        return series * np.nan
    return (series - series.mean(skipna=True)) / std


def load_sea_level() -> pd.DataFrame:
    with xr.open_dataset(SEA_NC) as ds:
        frame = ds[["sea_level_anomaly", "is_missing_month"]].to_dataframe()
    return frame


def load_local_calcofi() -> pd.DataFrame:
    with xr.open_dataset(CALCOFI_NC, engine="netcdf4") as ds:
        distance = ((ds.lat - LA_JOLLA_LAT) ** 2 + (ds.lon - LA_JOLLA_LON) ** 2) ** 0.5
        local = ds.isel(profile=(distance < LOCAL_RADIUS_DEG).values)
        surface = local.sel(depth=slice(0, SURFACE_M)).mean(dim="depth", skipna=True)

        df = (
            pd.DataFrame(
                {
                    "time": pd.to_datetime(local.time.values),
                    "temp": surface.Temp.values,
                    "salinity": surface.Salinity.values,
                }
            )
            .dropna(how="all")
            .set_index("time")
            .sort_index()
            .resample("MS")
            .mean()
        )
    return df


def build_merged_frame() -> tuple[pd.DataFrame, dict[str, float]]:
    sea = load_sea_level()
    cal = load_local_calcofi()

    overlap_start = max(sea.index.min(), cal.index.min())
    overlap_end = min(sea.index.max(), cal.index.max())
    monthly_index = pd.date_range(overlap_start, overlap_end, freq="MS")

    merged = sea.reindex(monthly_index).join(cal.reindex(monthly_index), how="left")
    merged.index.name = "time"

    merged["temp_anomaly"] = _monthly_anomaly(merged["temp"])
    merged["salinity_anomaly"] = _monthly_anomaly(merged["salinity"])

    merged["sea_z"] = _zscore(merged["sea_level_anomaly"])
    merged["temp_z"] = _zscore(merged["temp_anomaly"])
    merged["salinity_z"] = _zscore(merged["salinity_anomaly"])

    merged["sea_z_smooth"] = _smooth_monthly_segments(merged["sea_z"])
    merged["temp_z_smooth"] = _smooth_monthly_segments(merged["temp_z"])
    merged["salinity_z_smooth"] = _smooth_monthly_segments(merged["salinity_z"])

    complete = merged[
        ["sea_level_anomaly", "temp_anomaly", "salinity_anomaly"]
    ].dropna()
    stats = {
        "temp_corr": float(complete["sea_level_anomaly"].corr(complete["temp_anomaly"])),
        "salinity_corr": float(
            complete["sea_level_anomaly"].corr(complete["salinity_anomaly"])
        ),
        "complete_months": float(len(complete)),
    }
    return merged, stats


def plot_joint_chart(df: pd.DataFrame, stats: dict[str, float]) -> None:
    complete = df[["sea_level_anomaly", "temp_anomaly", "salinity_anomaly"]].dropna()

    fig = plt.figure(figsize=(12, 10), constrained_layout=True)
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.0, 1.0], hspace=0.35)

    ax_top = fig.add_subplot(gs[0, 0])
    ax_top.plot(
        df.index,
        df["sea_z_smooth"],
        color="tab:blue",
        lw=2.0,
        label="Sea level anomaly (z-score)",
    )
    ax_top.plot(
        df.index,
        df["temp_z_smooth"],
        color="tab:red",
        lw=2.0,
        label=f"Surface temp anomaly <= {SURFACE_M:.0f} m",
    )
    ax_top.plot(
        df.index,
        df["salinity_z_smooth"],
        color="tab:green",
        lw=2.0,
        label=f"Surface salinity anomaly <= {SURFACE_M:.0f} m",
    )
    ax_top.axhline(0.0, color="0.4", lw=0.8, ls="--")
    ax_top.set_ylabel("Standardized anomaly")
    ax_top.set_title(
        "La Jolla sea level vs nearby CalCOFI surface temperature and salinity"
    )
    ax_top.legend(loc="upper left")
    ax_top.text(
        0.01,
        0.02,
        (
            f"CalCOFI subset: within {LOCAL_RADIUS_DEG:.1f} degree of La Jolla, "
            f"monthly means, smoothed over 12 months\n"
            f"Complete overlapping months: {int(stats['complete_months'])}"
        ),
        transform=ax_top.transAxes,
        va="bottom",
        fontsize=9,
        color="0.25",
    )

    ax_mid = fig.add_subplot(gs[1, 0])
    sc1 = ax_mid.scatter(
        complete["temp_anomaly"],
        complete["sea_level_anomaly"],
        c=complete.index.year,
        cmap="plasma",
        s=16,
        alpha=0.8,
    )
    ax_mid.set_xlabel("Surface temp anomaly (deg C)")
    ax_mid.set_ylabel("Sea level anomaly (m)")
    ax_mid.set_title(f"Temperature coupling (r = {stats['temp_corr']:.2f})")
    plt.colorbar(sc1, ax=ax_mid, label="Year")

    ax_bot = fig.add_subplot(gs[2, 0])
    sc2 = ax_bot.scatter(
        complete["salinity_anomaly"],
        complete["sea_level_anomaly"],
        c=complete.index.year,
        cmap="viridis",
        s=16,
        alpha=0.8,
    )
    ax_bot.set_xlabel("Surface salinity anomaly (PSU)")
    ax_bot.set_ylabel("Sea level anomaly (m)")
    ax_bot.set_title(f"Salinity coupling (r = {stats['salinity_corr']:.2f})")
    plt.colorbar(sc2, ax=ax_bot, label="Year")

    fig.savefig(OUT / "coops_calcofi_joint_chart.png", dpi=140)
    plt.close(fig)


def plot_temp_salinity_coupling(df: pd.DataFrame) -> None:
    complete = df[["temp", "salinity", "temp_anomaly", "salinity_anomaly"]].dropna()

    fig, axes = plt.subplots(2, 1, figsize=(10, 9), constrained_layout=True)

    sc1 = axes[0].scatter(
        complete["salinity"],
        complete["temp"],
        c=complete.index.year,
        cmap="magma",
        s=18,
        alpha=0.8,
    )
    axes[0].set_xlabel("Surface salinity (PSU)")
    axes[0].set_ylabel("Surface temp (deg C)")
    axes[0].set_title("Nearby CalCOFI surface temperature vs salinity")
    plt.colorbar(sc1, ax=axes[0], label="Year")

    sc2 = axes[1].scatter(
        complete["salinity_anomaly"],
        complete["temp_anomaly"],
        c=complete.index.year,
        cmap="viridis",
        s=18,
        alpha=0.8,
    )
    axes[1].axhline(0.0, color="0.4", lw=0.8, ls="--")
    axes[1].axvline(0.0, color="0.4", lw=0.8, ls="--")
    axes[1].set_xlabel("Surface salinity anomaly (PSU)")
    axes[1].set_ylabel("Surface temp anomaly (deg C)")
    axes[1].set_title(
        f"Temperature-salinity anomaly coupling "
        f"(r = {complete['temp_anomaly'].corr(complete['salinity_anomaly']):.2f})"
    )
    plt.colorbar(sc2, ax=axes[1], label="Year")

    fig.savefig(OUT / "coops_calcofi_temp_salinity_coupling.png", dpi=140)
    plt.close(fig)


def main() -> None:
    merged, stats = build_merged_frame()
    plot_joint_chart(merged, stats)
    plot_temp_salinity_coupling(merged)
    print(f"Plots written to {OUT}")
    print(
        "Correlation summary: "
        f"temp={stats['temp_corr']:.3f}, salinity={stats['salinity_corr']:.3f}, "
        f"complete_months={int(stats['complete_months'])}"
    )


if __name__ == "__main__":
    main()
