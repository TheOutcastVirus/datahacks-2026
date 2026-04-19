"""Strip seasonal + short-term variability from La Jolla MSL to expose the trend.

Produces three candidate series so we can pick the cleanest one for the wide-
projection model:

1. `sla_deseasonalized`  -- raw MSL minus the month-of-year climatology.
                            (Same definition used elsewhere in the repo.)
2. `sla_ma12`            -- 12-month trailing moving average of (1).
3. `sla_annual`          -- calendar-year mean of raw MSL (coarsest but cleanest).

All three are plotted on one figure plus written out to `sla_normalized.csv`
for the forecasting model to consume.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from project_paths import PLOTS_DIR, PROCESSED_COOPS_NC, SLA_NORMALIZED_CSV


SEA_NC = PROCESSED_COOPS_NC
OUT_CSV = SLA_NORMALIZED_CSV
OUT_PLOT = PLOTS_DIR / "sla_normalization.png"
OUT_SEASONALITY = PLOTS_DIR / "sla_seasonality.png"


def load_msl() -> pd.Series:
    with xr.open_dataset(SEA_NC) as ds:
        msl = ds["msl"].to_series().sort_index()
    msl.index.name = "time"
    msl.name = "msl"
    return msl


def normalize(msl: pd.Series) -> pd.DataFrame:
    # Seasonal normalization: remove the monthly climatology.
    climatology = msl.groupby(msl.index.month).transform("mean")
    deseasonalized = (msl - climatology).rename("sla_deseasonalized")

    # Fallback smoothing: 12-month trailing MA of the deseasonalized series.
    ma12 = (
        deseasonalized.rolling(12, min_periods=12).mean().rename("sla_ma12")
    )

    # Coarse but clean: annual mean of raw MSL (keeps the absolute scale).
    annual = msl.resample("YS").mean().rename("sla_annual")
    annual = annual.reindex(msl.index).ffill()

    out = pd.concat([msl, deseasonalized, ma12, annual], axis=1)
    return out


def plot(df: pd.DataFrame) -> None:
    OUT_PLOT.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(4, 1, figsize=(11, 11), sharex=True)

    axes[0].plot(df.index, df["msl"], color="tab:gray", lw=0.7, alpha=0.6, label="raw MSL")
    axes[0].plot(
        df.index, df["msl"].rolling(12, min_periods=12).mean(),
        color="black", lw=1.6, label="12-mo trailing mean",
    )
    axes[0].set(ylabel="MSL (m)", title="Raw MSL with 12-month trailing mean")
    axes[0].legend(loc="best", fontsize=9)

    axes[1].axhline(0, color="k", lw=0.5, alpha=0.5)
    axes[1].plot(
        df.index, df["sla_deseasonalized"], color="tab:blue", lw=0.8, alpha=0.6,
        label="deseasonalized (raw MSL - monthly climatology)",
    )
    axes[1].plot(
        df.index, df["sla_ma12"], color="navy", lw=1.8,
        label="12-mo trailing MA of deseasonalized",
    )
    axes[1].set(
        ylabel="SLA (m)",
        title="Deseasonalized SLA — should rise year over year if seasonal strip is enough",
    )
    axes[1].legend(loc="best", fontsize=9)

    axes[2].plot(
        df.index, df["sla_annual"], color="tab:red", lw=2.0, label="calendar-year mean of MSL",
    )
    # Linear fit on the annual series for visual reference.
    annual = df["sla_annual"].dropna()
    if len(annual) > 2:
        t_years = (annual.index.year + (annual.index.month - 1) / 12).values
        coef = np.polyfit(t_years, annual.values, 1)
        fit = np.polyval(coef, t_years)
        axes[2].plot(
            annual.index, fit, color="black", ls="--", lw=1.2,
            label=f"linear fit: {coef[0] * 1000:+.2f} mm/yr",
        )
    axes[2].set(
        ylabel="MSL (m)", title="Annual mean — coarsest but cleanest trend",
    )
    axes[2].legend(loc="best", fontsize=9)

    # Panel 4: annual mean with deseasonalized SLA overlaid (twin-y so scales stay readable).
    ax_left = axes[3]
    ax_left.plot(
        df.index, df["sla_annual"], color="tab:red", lw=2.0, label="annual mean MSL",
    )
    ax_left.set_ylabel("annual MSL (m)", color="tab:red")
    ax_left.tick_params(axis="y", labelcolor="tab:red")

    ax_right = ax_left.twinx()
    ax_right.axhline(0, color="k", lw=0.5, alpha=0.3)
    ax_right.plot(
        df.index, df["sla_deseasonalized"], color="tab:blue", lw=0.6, alpha=0.5,
        label="deseasonalized SLA (monthly)",
    )
    ax_right.plot(
        df.index, df["sla_ma12"], color="navy", lw=1.6,
        label="12-mo MA of deseasonalized",
    )
    ax_right.set_ylabel("deseasonalized SLA (m)", color="tab:blue")
    ax_right.tick_params(axis="y", labelcolor="tab:blue")

    lines_l, labels_l = ax_left.get_legend_handles_labels()
    lines_r, labels_r = ax_right.get_legend_handles_labels()
    ax_left.legend(lines_l + lines_r, labels_l + labels_r, loc="best", fontsize=9)
    ax_left.set(
        xlabel="Time",
        title="Annual mean MSL with deseasonalized SLA overlay",
    )

    fig.tight_layout()
    fig.savefig(OUT_PLOT, dpi=130)
    plt.close(fig)
    print(f"wrote {OUT_PLOT}")


def plot_seasonality(df: pd.DataFrame) -> None:
    """Stack each calendar year's 12-month MSL cycle to expose seasonality."""
    OUT_SEASONALITY.parent.mkdir(parents=True, exist_ok=True)
    series = df["msl"].dropna()
    by_year = series.groupby(series.index.year)

    fig, axes = plt.subplots(2, 1, figsize=(11, 8))

    ax = axes[0]
    years = sorted(by_year.groups.keys())
    cmap = plt.get_cmap("viridis")
    for y in years:
        s = by_year.get_group(y)
        if len(s) < 6:
            continue
        ax.plot(
            s.index.month, s.values,
            color=cmap((y - years[0]) / max(1, years[-1] - years[0])),
            lw=0.6, alpha=0.5,
        )

    # Overlay the month-of-year climatology with +/- 1 sigma.
    clim = series.groupby(series.index.month).agg(["mean", "std"])
    ax.errorbar(
        clim.index, clim["mean"], yerr=clim["std"],
        fmt="o-", color="crimson", capsize=3, lw=2.0,
        label=f"climatology mean +/- 1 sigma (sigma={clim['std'].mean():.3f} m)",
    )
    ax.set(
        xticks=range(1, 13),
        xlabel="calendar month", ylabel="raw MSL (m)",
        title="Raw MSL annual cycle, one line per year (1949-2021)",
    )
    ax.legend(loc="best", fontsize=9)

    # Same view for the deseasonalized series; if seasonality was fully removed,
    # all year-lines should collapse onto a flat band near zero.
    ax = axes[1]
    des = df["sla_deseasonalized"].dropna()
    by_year_des = des.groupby(des.index.year)
    for y in years:
        if y not in by_year_des.groups:
            continue
        s = by_year_des.get_group(y)
        if len(s) < 6:
            continue
        ax.plot(
            s.index.month, s.values,
            color=cmap((y - years[0]) / max(1, years[-1] - years[0])),
            lw=0.6, alpha=0.5,
        )
    clim_des = des.groupby(des.index.month).agg(["mean", "std"])
    ax.errorbar(
        clim_des.index, clim_des["mean"], yerr=clim_des["std"],
        fmt="o-", color="crimson", capsize=3, lw=2.0,
        label="deseasonalized climatology (should be ~zero mean)",
    )
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    ax.set(
        xticks=range(1, 13),
        xlabel="calendar month", ylabel="deseasonalized SLA (m)",
        title="Deseasonalized SLA annual cycle — residual seasonal structure (if any)",
    )
    ax.legend(loc="best", fontsize=9)

    # Color bar for year.
    sm = plt.cm.ScalarMappable(
        cmap=cmap,
        norm=plt.Normalize(vmin=years[0], vmax=years[-1]),
    )
    cbar = fig.colorbar(sm, ax=axes, orientation="vertical", pad=0.02, shrink=0.85)
    cbar.set_label("year")

    fig.savefig(OUT_SEASONALITY, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OUT_SEASONALITY}")


def main() -> None:
    msl = load_msl()
    print(f"Loaded MSL: {len(msl)} months, {msl.index.min():%Y-%m} -> {msl.index.max():%Y-%m}")
    print(f"  raw range: {msl.min():.3f} -> {msl.max():.3f} m")

    df = normalize(msl)
    for col in ["sla_deseasonalized", "sla_ma12", "sla_annual"]:
        s = df[col].dropna()
        if s.empty:
            continue
        print(
            f"  {col:22s} n={len(s):4d}  mean={s.mean():+.4f}  "
            f"std={s.std():.4f}  range={s.min():+.4f} .. {s.max():+.4f}"
        )

    df.to_csv(OUT_CSV)
    print(f"wrote {OUT_CSV}")
    plot(df)
    plot_seasonality(df)


if __name__ == "__main__":
    main()
