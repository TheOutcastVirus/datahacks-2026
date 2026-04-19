"""Explore argo_heat700_monthly.csv: shape, coverage, and preliminary plots.

Kernel-safe: no __file__. Resolves the data path via cwd.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from project_paths import PLOTS_DIR, PROCESSED_ARGO_CSV, PROCESSED_COOPS_NC


ARGO_CSV = PROCESSED_ARGO_CSV
SEA_NC = PROCESSED_COOPS_NC
OUT_DIR = PLOTS_DIR
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_argo() -> pd.DataFrame:
    df = pd.read_csv(ARGO_CSV, parse_dates=["time"]).set_index("time").sort_index()
    print(f"Loaded {ARGO_CSV.name}")
    print(f"  shape: {df.shape}")
    print(f"  columns: {list(df.columns)}")
    print(f"  time range: {df.index.min():%Y-%m} -> {df.index.max():%Y-%m}")
    print(f"  months with data: {df['heat700'].notna().sum()} / {len(df)}")
    print(f"  total profiles in box: {int(df['n_profiles'].fillna(0).sum()):,}")
    return df


def describe(df: pd.DataFrame) -> None:
    print("\n=== Summary stats ===")
    print(df.describe().to_string())
    print("\n=== Head ===")
    print(df.head().to_string())
    print("\n=== Tail ===")
    print(df.tail().to_string())


def plot_profile_counts(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.bar(df.index, df["n_profiles"].fillna(0), width=20, color="tab:gray")
    ax.set(title="Argo profiles per month in NE Pacific box", ylabel="# profiles")
    fig.tight_layout()
    path = OUT_DIR / "argo_profile_counts.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")


def plot_heat_series(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    axes[0].plot(df.index, df["heat700"], color="tab:red", lw=1.2)
    axes[0].set(ylabel="heat700 (degC*dbar)", title="Monthly 0-700 dbar heat content proxy")
    axes[1].axhline(0, color="k", lw=0.5, alpha=0.5)
    axes[1].plot(df.index, df["heat700_anomaly"], color="tab:blue", lw=1.2)
    smooth = df["heat700_anomaly"].rolling(5, center=True, min_periods=3).mean()
    axes[1].plot(df.index, smooth, color="navy", lw=1.8, alpha=0.8, label="5-mo smooth")
    axes[1].set(ylabel="heat700 anomaly", xlabel="time")
    axes[1].legend(loc="best", fontsize=8)
    fig.tight_layout()
    path = OUT_DIR / "argo_heat_timeseries.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")


def plot_climatology(df: pd.DataFrame) -> None:
    clim = df.groupby(df.index.month)["heat700"].agg(["mean", "std", "count"])
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.errorbar(clim.index, clim["mean"], yerr=clim["std"], fmt="o-", color="tab:red", capsize=3)
    ax.set(
        title="Monthly climatology of 0-700 dbar heat content",
        xlabel="month",
        ylabel="heat700 (degC*dbar)",
        xticks=range(1, 13),
    )
    fig.tight_layout()
    path = OUT_DIR / "argo_climatology.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")


def plot_vs_sea_level(df: pd.DataFrame) -> None:
    if not SEA_NC.exists():
        print(f"Skipping SLA comparison; {SEA_NC.name} not found.")
        return
    try:
        import xarray as xr
    except ImportError:
        print("xarray missing; skipping SLA overlay.")
        return

    with xr.open_dataset(SEA_NC) as ds:
        sea = ds["sea_level_anomaly"].to_dataframe().sort_index()
    sea_monthly = sea["sea_level_anomaly"].resample("MS").mean()

    joined = pd.concat(
        [df["heat700_anomaly"].rename("argo_heat700_anom"), sea_monthly.rename("sla")],
        axis=1,
    ).dropna()
    if joined.empty:
        print("No overlap between Argo and SLA.")
        return

    # Leading cross-correlation: does heat700 at t-k predict SLA at t?
    max_lag = 18
    lags = range(-max_lag, max_lag + 1)
    corrs = []
    for lag in lags:
        if lag >= 0:
            c = joined["argo_heat700_anom"].shift(lag).corr(joined["sla"])
        else:
            c = joined["argo_heat700_anom"].corr(joined["sla"].shift(-lag))
        corrs.append(c)
    best = max(range(len(lags)), key=lambda i: corrs[i])
    best_lag = list(lags)[best]
    print(
        f"\nArgo heat700 vs SLA: best Pearson r = {corrs[best]:+.3f} at lag = {best_lag} months "
        f"(positive => heat leads SLA)"
    )

    fig, axes = plt.subplots(2, 1, figsize=(11, 6))
    ax = axes[0]
    ax.plot(
        joined.index,
        (joined["argo_heat700_anom"] - joined["argo_heat700_anom"].mean())
        / joined["argo_heat700_anom"].std(),
        color="tab:red",
        label="Argo heat700 anom (z)",
    )
    ax.plot(
        joined.index,
        (joined["sla"] - joined["sla"].mean()) / joined["sla"].std(),
        color="tab:blue",
        label="La Jolla SLA (z)",
    )
    ax.set(title="Argo heat700 vs La Jolla SLA (z-scored)", ylabel="z-score")
    ax.legend(loc="best", fontsize=9)

    ax = axes[1]
    ax.axhline(0, color="k", lw=0.5)
    ax.axvline(0, color="k", lw=0.5, ls=":")
    ax.plot(list(lags), corrs, color="tab:purple", marker="o", ms=3)
    ax.axvline(best_lag, color="tab:purple", ls="--", alpha=0.6, label=f"best lag={best_lag}")
    ax.set(
        title="Lagged correlation: heat700(t+lag) vs SLA(t)  "
        "(lag>0: heat leads SLA)",
        xlabel="lag (months)",
        ylabel="Pearson r",
    )
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    path = OUT_DIR / "argo_vs_sla.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")


def main() -> None:
    df = load_argo()
    describe(df)
    plot_profile_counts(df)
    plot_heat_series(df)
    plot_climatology(df)
    plot_vs_sea_level(df)
    print(f"\nAll plots written to {OUT_DIR}")


if __name__ == "__main__":
    main()
