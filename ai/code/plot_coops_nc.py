"""Create preliminary plots from the La Jolla CO-OPS NetCDF time series."""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from project_paths import PLOTS_DIR, PROCESSED_COOPS_NC


NC = PROCESSED_COOPS_NC
OUT = PLOTS_DIR
OUT.mkdir(parents=True, exist_ok=True)


def load_dataset(path: Path) -> xr.Dataset:
    with xr.open_dataset(path) as opened:
        return opened.load()


def to_frame(ds: xr.Dataset) -> pd.DataFrame:
    df = ds[
        [
            "msl",
            "sea_level_anomaly",
            "highest",
            "lowest",
            "month_number",
            "year",
            "is_missing_month",
            "is_flagged_or_infilled",
        ]
    ].to_dataframe()
    df["monthly_range"] = df["highest"] - df["lowest"]
    df["msl_12mo"] = df["msl"].rolling(window=12, min_periods=6).mean()
    return df


def plot_long_term(df: pd.DataFrame, station_name: str) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    axes[0].plot(df.index, df["msl"], color="tab:blue", lw=0.8, alpha=0.45)
    axes[0].plot(df.index, df["msl_12mo"], color="navy", lw=2.0)
    axes[0].set_ylabel("MSL (m)")
    axes[0].set_title(f"{station_name} monthly mean sea level")

    axes[1].axhline(0.0, color="0.3", lw=0.8, ls="--")
    axes[1].plot(df.index, df["sea_level_anomaly"], color="tab:orange", lw=0.9)
    axes[1].set_ylabel("Anomaly (m)")
    axes[1].set_title("Monthly mean sea level anomaly")

    fig.tight_layout()
    fig.savefig(OUT / "coops_long_term_timeseries.png", dpi=140)
    plt.close(fig)


def plot_seasonality(ds: xr.Dataset, station_name: str) -> None:
    climatology = ds["msl_monthly_climatology"].to_series()

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(climatology.index, climatology.values, color="tab:green", lw=2)
    ax.scatter(climatology.index, climatology.values, color="tab:green", s=28)
    ax.set_xticks(np.arange(1, 13))
    ax.set_xlabel("Month")
    ax.set_ylabel("Climatological MSL (m)")
    ax.set_title(f"{station_name} monthly sea level climatology")
    fig.tight_layout()
    fig.savefig(OUT / "coops_monthly_climatology.png", dpi=140)
    plt.close(fig)


def plot_anomaly_heatmap(df: pd.DataFrame, station_name: str) -> None:
    valid = df[df["is_missing_month"] == 0].copy()
    heatmap = valid.pivot(index="year", columns="month_number", values="sea_level_anomaly")

    fig, ax = plt.subplots(figsize=(12, 8))
    vmax = np.nanmax(np.abs(heatmap.to_numpy()))
    im = ax.imshow(
        heatmap.to_numpy(),
        aspect="auto",
        origin="lower",
        cmap="coolwarm",
        vmin=-vmax,
        vmax=vmax,
    )
    ax.set_xticks(np.arange(12))
    ax.set_xticklabels(np.arange(1, 13))
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")
    ax.set_yticks(np.arange(0, len(heatmap.index), 10))
    ax.set_yticklabels(heatmap.index[::10])
    ax.set_title(f"{station_name} sea level anomaly heatmap")
    plt.colorbar(im, ax=ax, label="Anomaly (m)")
    fig.tight_layout()
    fig.savefig(OUT / "coops_anomaly_heatmap.png", dpi=140)
    plt.close(fig)


def plot_quality_and_extremes(df: pd.DataFrame, station_name: str) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    axes[0].plot(df.index, df["monthly_range"], color="tab:purple", lw=1.0)
    axes[0].set_ylabel("Range (m)")
    axes[0].set_title(f"{station_name} monthly high-low water range")

    flag_y = np.where(df["is_flagged_or_infilled"] > 0, 1.0, 0.0)
    miss_y = np.where(df["is_missing_month"] > 0, 0.4, 0.0)
    axes[1].scatter(df.index, flag_y, s=10, color="tab:red", label="Flagged/infilled")
    axes[1].scatter(df.index, miss_y, s=10, color="0.35", label="Missing month")
    axes[1].set_ylim(-0.1, 1.2)
    axes[1].set_yticks([0.0, 0.4, 1.0])
    axes[1].set_yticklabels(["none", "missing", "flagged"])
    axes[1].set_title("Data quality markers")
    axes[1].legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(OUT / "coops_quality_and_extremes.png", dpi=140)
    plt.close(fig)


def main() -> None:
    ds = load_dataset(NC)
    station_name = ds.attrs.get("station_name", "CO-OPS station")
    df = to_frame(ds)

    plot_long_term(df, station_name)
    plot_seasonality(ds, station_name)
    plot_anomaly_heatmap(df, station_name)
    plot_quality_and_extremes(df, station_name)
    print(f"Plots written to {OUT}")


if __name__ == "__main__":
    main()
