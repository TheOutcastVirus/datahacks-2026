"""Long-horizon SLA forecast: linear SLR trend + NN residual inter-annual term.

Architecture decision (option B):
- The secular sea-level-rise trend is fit with a linear regression on raw MSL
  across the full record. That trend is authoritative for long-horizon projection.
- The NN is trained to predict the *residual trend* (sla_ma12 minus the linear
  trend). It therefore only models the inter-annual wiggle (ENSO etc.), not the
  secular rise. Its mean output is zero by construction, so autoregressive
  rollouts cannot drift the forecast below the linear trend.
- Final trend = linear_trend(t) + NN_residual_prediction(t).

Feature design:
- Input features per month: wide-radius CalCOFI temp anomaly + its 6- and 12-mo
  rolling means, and the trend-residual (sla_ma12_detrended) as a stateful anchor.
- Wide CalCOFI radius (default 10 deg) chosen because local temp is contemporaneous
  with local SLA; temperature farther offshore may lead coastal SLA by months.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import xarray as xr
from torch import nn

from project_paths import (
    PLOTS_DIR,
    PROCESSED_CALCOFI_NC,
    PROCESSED_COOPS_NC,
    SLA_PREDICTION_CSV,
)


# ---- config -----------------------------------------------------------------

LA_JOLLA_LAT = 32.867
LA_JOLLA_LON = -117.257
WIDE_RADIUS_DEG = 10.0  # expand the CalCOFI aggregation circle
SURFACE_M = 10.0

WINDOW = 12        # months of features fed to the NN
HORIZON = 6        # months ahead to predict
MA_WINDOW = 12     # trailing MA window on deseasonalized SLA
TRAIN_END = pd.Timestamp("2010-01-01")

HIDDEN = 32
EPOCHS = 1200
LR = 3e-3
WEIGHT_DECAY = 1e-3
SEED = 0

ROLLOUT_YEARS = 50  # autoregressive forecast horizon beyond the last observation

SEA_NC = PROCESSED_COOPS_NC
CALCOFI_NC = PROCESSED_CALCOFI_NC
OUT_PLOT = PLOTS_DIR / "simple_dnn_full_history_wide_projection.png"
OUT_CSV = SLA_PREDICTION_CSV


# ---- data loading -----------------------------------------------------------


def load_msl() -> pd.Series:
    with xr.open_dataset(SEA_NC) as ds:
        msl = ds["msl"].to_series().sort_index()
    msl.index = pd.DatetimeIndex(msl.index)
    msl.name = "msl"
    return msl


def load_wide_calcofi_temp(radius_deg: float) -> pd.Series:
    """Monthly surface (<=10 m) temperature anomaly over a wide circle.

    CalCOFI cruises are irregular (~quarterly in recent decades), so the
    straight monthly resample has gaps. We interpolate short gaps before
    computing the climatology and rolling means so the downstream feature
    frame doesn't evaporate to zero rows.
    """
    with xr.open_dataset(CALCOFI_NC, engine="netcdf4") as ds:
        distance = (
            (ds.lat - LA_JOLLA_LAT) ** 2 + (ds.lon - LA_JOLLA_LON) ** 2
        ) ** 0.5
        mask = (distance < radius_deg).values
        sub = ds.isel(profile=mask)
        surface = sub.sel(depth=slice(0, SURFACE_M)).mean(dim="depth", skipna=True)
        raw = (
            pd.DataFrame(
                {
                    "time": pd.to_datetime(sub.time.values),
                    "temp": surface.Temp.values,
                }
            )
            .dropna()
            .set_index("time")
            .sort_index()
        )
    # Full monthly grid spanning the CalCOFI range, then interpolate gaps up to 6 months.
    monthly_index = pd.date_range(
        raw.index.min().to_period("M").to_timestamp(),
        raw.index.max().to_period("M").to_timestamp(),
        freq="MS",
    )
    monthly = raw["temp"].resample("MS").mean().reindex(monthly_index)
    monthly = monthly.interpolate("time", limit=6, limit_area="inside")
    climatology = monthly.groupby(monthly.index.month).transform("mean")
    anomaly = (monthly - climatology).rename("temp_wide_anomaly")
    return anomaly


# ---- feature engineering ----------------------------------------------------


def build_feature_frame(
    radius_deg: float,
) -> tuple[pd.DataFrame, pd.Series, float, float]:
    msl = load_msl()

    # Linear trend fit on raw MSL; used both to detrend the climatology and to
    # detrend sla_ma12 so the NN only sees the residual wiggle.
    t_years = (msl.index.year + (msl.index.month - 1) / 12.0).to_numpy(dtype=float)
    valid = msl.notna().to_numpy()
    trend_coef = np.polyfit(t_years[valid], msl.to_numpy(dtype=float)[valid], 1)
    slope = float(trend_coef[0])
    intercept = float(trend_coef[1])
    linear_trend_msl = pd.Series(np.polyval(trend_coef, t_years), index=msl.index)

    # Detrended climatology (relative seasonal cycle, centered near zero).
    detrended_msl = msl - linear_trend_msl
    clim_by_month = detrended_msl.groupby(detrended_msl.index.month).mean()
    clim_by_month.name = "msl_climatology_detrended"

    climatology_full = pd.Series(
        msl.index.month.map(clim_by_month).astype(float).to_numpy(),
        index=msl.index,
    )
    sla = (msl - climatology_full).rename("sla_deseasonalized")
    sla_ma = sla.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean().rename("sla_ma12")

    # sla_ma12 minus linear trend at the same dates. This is the residual-trend
    # series the NN will actually predict.
    sla_ma_detrended = (sla_ma - linear_trend_msl).rename("sla_ma12_detrended")

    temp_anom = load_wide_calcofi_temp(radius_deg)
    temp_roll_6 = temp_anom.rolling(6, min_periods=6).mean().rename("temp_wide_roll_6")
    temp_roll_12 = temp_anom.rolling(12, min_periods=12).mean().rename("temp_wide_roll_12")

    df = pd.concat(
        [sla, sla_ma, sla_ma_detrended, temp_anom, temp_roll_6, temp_roll_12], axis=1
    )
    df = df.dropna()
    print(
        f"Linear trend fit: slope={slope * 1000:+.2f} mm/yr, intercept={intercept:+.4f} m"
    )
    print(
        f"Detrended climatology (relative seasonal cycle): "
        f"min={clim_by_month.min():+.4f} max={clim_by_month.max():+.4f} "
        f"mean={clim_by_month.mean():+.4f}"
    )
    print(
        f"sla_ma12_detrended range: {df['sla_ma12_detrended'].min():+.4f} .. "
        f"{df['sla_ma12_detrended'].max():+.4f} (centered near zero if trend is linear)"
    )
    return df, clim_by_month, slope, intercept


def linear_trend_at(dates: pd.DatetimeIndex, slope: float, intercept: float) -> np.ndarray:
    t_years = (dates.year + (dates.month - 1) / 12.0).to_numpy(dtype=float)
    return (slope * t_years + intercept).astype(np.float32)


# ---- windowing --------------------------------------------------------------


def make_windows(
    features: np.ndarray, trend: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Residual trend target: y = trend[t+WINDOW+HORIZON-1] - trend[t+WINDOW-1].

    Returns (x, y_delta, anchor). `anchor` is the last observed trend value in
    the input window so the absolute trend prediction is anchor + y_delta.
    """
    x, y, anchor = [], [], []
    n = len(trend)
    for i in range(n - WINDOW - HORIZON + 1):
        feat_window = features[i : i + WINDOW]
        anchor_val = trend[i + WINDOW - 1]
        target_val = trend[i + WINDOW + HORIZON - 1]
        if (
            np.isfinite(feat_window).all()
            and np.isfinite(anchor_val)
            and np.isfinite(target_val)
        ):
            x.append(feat_window.reshape(-1))
            y.append(target_val - anchor_val)
            anchor.append(anchor_val)
    return (
        np.asarray(x, dtype=np.float32),
        np.asarray(y, dtype=np.float32).reshape(-1, 1),
        np.asarray(anchor, dtype=np.float32),
    )


# ---- model ------------------------------------------------------------------


class DenseNet(nn.Module):
    def __init__(self, in_dim: int, out_dim: int, hidden: int = HIDDEN):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ---- autoregressive rollout -------------------------------------------------


def rollout_forecast(
    model: nn.Module,
    device: str,
    df: pd.DataFrame,
    feature_cols: list[str],
    x_mu: np.ndarray,
    x_sd: np.ndarray,
    y_mu: np.ndarray,
    y_sd: np.ndarray,
    years: int,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Roll the trained model forward `years` years past the end of `df`.

    The NN predicts residual-from-linear-trend, so the rollout operates purely
    on the detrended series. The linear trend is added back *outside* this
    function to get absolute SLA. Future temperature features are set to 0
    (climatology) since we have no temp forecast.
    """
    sla_series = df["sla_ma12_detrended"].copy().astype(float)

    last_date = df.index[-1]
    steps = int(np.ceil(years * 12 / HORIZON))
    future_end = last_date + pd.DateOffset(months=steps * HORIZON)
    future_index = pd.date_range(
        start=last_date + pd.DateOffset(months=1),
        end=future_end,
        freq="MS",
    )
    sla_series = pd.concat(
        [sla_series, pd.Series(np.nan, index=future_index)]
    )

    model.eval()
    k = len(feature_cols)

    current_end = last_date
    for _ in range(steps):
        window_end_idx = sla_series.index.get_loc(current_end)
        window_slice = slice(window_end_idx - WINDOW + 1, window_end_idx + 1)
        sla_window = sla_series.iloc[window_slice].to_numpy(dtype=np.float32)
        # Future temp features: unknown -> climatology (0 anomaly). For historical
        # months inside the window we use the actual wide-box values when they
        # are present.
        temp_window = np.zeros(WINDOW, dtype=np.float32)
        temp_roll_6_window = np.zeros(WINDOW, dtype=np.float32)
        temp_roll_12_window = np.zeros(WINDOW, dtype=np.float32)
        window_dates = sla_series.index[window_slice]
        for j, d in enumerate(window_dates):
            if d in df.index:
                temp_window[j] = df.at[d, "temp_wide_anomaly"]
                temp_roll_6_window[j] = df.at[d, "temp_wide_roll_6"]
                temp_roll_12_window[j] = df.at[d, "temp_wide_roll_12"]
        # sla_window already contains residual-trend values (observed + predicted).
        feat = np.stack(
            [sla_window, temp_window, temp_roll_6_window, temp_roll_12_window],
            axis=1,
        )
        if feature_cols != [
            "sla_ma12_detrended", "temp_wide_anomaly", "temp_wide_roll_6", "temp_wide_roll_12"
        ]:
            raise RuntimeError("Feature order hard-coded in rollout; update here if you change it.")
        x_input = feat.reshape(-1)
        x_input_n = (x_input - x_mu) / x_sd
        with torch.no_grad():
            delta_n = model(torch.from_numpy(x_input_n[None, :]).to(device)).cpu().numpy()
        delta = float((delta_n * y_sd + y_mu).reshape(-1)[0])

        anchor_val = float(sla_window[-1])
        new_trend = anchor_val + delta  # residual-trend scale (no SLR added here)

        future_dates = pd.date_range(
            start=current_end + pd.DateOffset(months=1),
            periods=HORIZON,
            freq="MS",
        )
        # Linearly interpolate the trend between anchor and new_trend so the next
        # window has a smooth monotonic filling.
        interp_vals = np.linspace(anchor_val, new_trend, HORIZON + 1, dtype=np.float32)[1:]
        sla_series.loc[future_dates] = interp_vals

        current_end = future_dates[-1]

    future_trend = sla_series.loc[future_index].to_numpy(dtype=np.float32)
    return future_index, future_trend


# ---- main -------------------------------------------------------------------


def main() -> None:
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    df, clim_by_month, slr_rate, slr_intercept = build_feature_frame(WIDE_RADIUS_DEG)
    print(
        f"Feature frame: {len(df)} months "
        f"({df.index.min():%Y-%m} -> {df.index.max():%Y-%m})  radius={WIDE_RADIUS_DEG} deg"
    )

    feature_cols = [
        "sla_ma12_detrended", "temp_wide_anomaly", "temp_wide_roll_6", "temp_wide_roll_12",
    ]
    features = df[feature_cols].to_numpy(dtype=np.float32)
    trend_residual = df["sla_ma12_detrended"].to_numpy(dtype=np.float32)

    x, y, anchor = make_windows(features, trend_residual)
    print(
        f"Windowed samples: {len(x)}  x-shape={x.shape}  y-shape={y.shape}  "
        f"(WINDOW={WINDOW}, HORIZON={HORIZON})"
    )

    target_dates = df.index[WINDOW + HORIZON - 1 : WINDOW + HORIZON - 1 + len(x)]
    split = int((target_dates < TRAIN_END).sum())
    if split < 24 or split >= len(x):
        raise ValueError(
            f"Bad date split: {split} train / {len(x) - split} val "
            f"(TRAIN_END={TRAIN_END.date()})."
        )
    print(
        f"Train target dates: {target_dates[0]:%Y-%m} -> {target_dates[split - 1]:%Y-%m} "
        f"({split} windows)"
    )
    print(
        f"Val   target dates: {target_dates[split]:%Y-%m} -> {target_dates[-1]:%Y-%m} "
        f"({len(x) - split} windows)"
    )

    x_train, x_val = x[:split], x[split:]
    y_train, y_val = y[:split], y[split:]
    anchor_train, anchor_val = anchor[:split], anchor[split:]

    x_mu, x_sd = x_train.mean(axis=0), x_train.std(axis=0)
    x_sd[x_sd == 0] = 1.0
    y_mu, y_sd = y_train.mean(axis=0), y_train.std(axis=0)
    y_sd[y_sd == 0] = 1.0

    x_train_n = (x_train - x_mu) / x_sd
    x_val_n = (x_val - x_mu) / x_sd
    y_train_n = (y_train - y_mu) / y_sd

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = DenseNet(in_dim=x.shape[1], out_dim=1).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    loss_fn = nn.MSELoss()

    xt = torch.from_numpy(x_train_n).to(device)
    yt = torch.from_numpy(y_train_n).to(device)
    xv = torch.from_numpy(x_val_n).to(device)

    for epoch in range(1, EPOCHS + 1):
        model.train()
        opt.zero_grad()
        pred = model(xt)
        loss = loss_fn(pred, yt)
        loss.backward()
        opt.step()
        if epoch % 100 == 0 or epoch == 1:
            print(f"epoch {epoch:4d}  train_mse(norm)={loss.item():.4f}")

    model.eval()
    with torch.no_grad():
        pred_n = model(xv).cpu().numpy()
    pred_delta = (pred_n * y_sd + y_mu).reshape(-1)
    actual_delta = y_val.reshape(-1)

    val_target_dates = target_dates[split:]
    # The NN predicts residual-trend deltas. Reconstruct the residual trend,
    # then add the linear SLR component evaluated at the target dates to get
    # absolute sla_ma12.
    pred_residual = anchor_val + pred_delta
    actual_residual = anchor_val + actual_delta
    linear_at_val = linear_trend_at(val_target_dates, slr_rate, slr_intercept)
    pred_trend = pred_residual + linear_at_val
    actual_trend = actual_residual + linear_at_val

    rmse_nn = float(np.sqrt(np.mean((pred_trend - actual_trend) ** 2)))
    mae_nn = float(np.mean(np.abs(pred_trend - actual_trend)))
    # Persistence on the ABSOLUTE trend: last anchor + linear increment to target date.
    anchor_dates = target_dates[split:]  # same length as anchor_val
    # anchor-month dates are HORIZON months before target_dates
    anchor_month_dates = anchor_dates - pd.DateOffset(months=HORIZON)
    linear_at_anchor = linear_trend_at(anchor_month_dates, slr_rate, slr_intercept)
    anchor_trend = anchor_val + linear_at_anchor  # absolute sla_ma12 at anchor date
    rmse_persist = float(np.sqrt(np.mean((anchor_trend - actual_trend) ** 2)))
    # Linear-only baseline: trend at anchor + slope * HORIZON/12.
    pure_linear_preds = anchor_trend + slr_rate * (HORIZON / 12.0)
    rmse_linear_only = float(np.sqrt(np.mean((pure_linear_preds - actual_trend) ** 2)))
    # Local linear extrapolation of the last WINDOW residual values (then + linear).
    sla_ma_col = feature_cols.index("sla_ma12_detrended")
    k = len(feature_cols)
    ma_history_val = x_val[:, sla_ma_col::k]
    t_hist = np.arange(WINDOW, dtype=np.float32)
    lin_preds_residual = np.empty(len(x_val), dtype=np.float32)
    for i in range(len(x_val)):
        coef = np.polyfit(t_hist, ma_history_val[i], 1)
        lin_preds_residual[i] = np.polyval(coef, WINDOW - 1 + HORIZON)
    lin_preds = lin_preds_residual + linear_at_val
    rmse_lin = float(np.sqrt(np.mean((lin_preds - actual_trend) ** 2)))

    print()
    print(f"Val samples: {len(actual_trend)}")
    print(f"NN RMSE on absolute trend (sla_ma12 at t+{HORIZON} mo): {rmse_nn:.4f}")
    print(f"NN MAE:                                                 {mae_nn:.4f}")
    print(f"Persistence (anchor trend, no change) RMSE:             {rmse_persist:.4f}")
    print(f"Linear-only (anchor + SLR) RMSE:                        {rmse_linear_only:.4f}")
    print(f"Local linear extrap of last {WINDOW} mo RMSE:             {rmse_lin:.4f}")

    # For the raw-MSL plot we also want the seasonal add-back applied to the trend.
    val_months = val_target_dates.month
    seasonal_add = np.array([clim_by_month.loc[m] for m in val_months], dtype=np.float32)
    pred_msl = pred_trend + seasonal_add
    actual_msl = actual_trend + seasonal_add
    plot_start = val_target_dates.min()
    plot_end = val_target_dates.max()
    df_val = df.loc[plot_start:plot_end]

    # --- autoregressive rollout --------------------------------------------
    future_index, future_residual = rollout_forecast(
        model, device, df, feature_cols,
        x_mu, x_sd, y_mu, y_sd,
        years=ROLLOUT_YEARS,
    )
    # NN returns residual-trend values; add the linear SLR component to get absolute.
    linear_at_future = linear_trend_at(future_index, slr_rate, slr_intercept)
    future_trend = future_residual + linear_at_future

    future_months = future_index.month
    future_seasonal = np.array(
        [clim_by_month.loc[m] for m in future_months], dtype=np.float32
    )
    future_msl = future_trend + future_seasonal

    # Pure-linear reference: same linear trend, zero NN contribution.
    last_trend = float(df["sla_ma12"].iloc[-1])
    linear_future_trend = linear_at_future
    linear_future_msl = linear_future_trend + future_seasonal

    nn_total_rise = future_trend[-1] - last_trend
    linear_total_rise = linear_future_trend[-1] - last_trend
    print(
        f"Rollout: {len(future_index)} months projected "
        f"({future_index[0]:%Y-%m} -> {future_index[-1]:%Y-%m})"
    )
    print(
        f"  NN+SLR trend rise:   {nn_total_rise:+.4f} m  "
        f"({nn_total_rise * 1000 / ROLLOUT_YEARS:+.2f} mm/yr over rollout)"
    )
    print(
        f"  linear-only trend rise: {linear_total_rise:+.4f} m  "
        f"({slr_rate * 1000:+.2f} mm/yr = historical fit)"
    )
    print(
        f"  NN inter-annual contribution: {nn_total_rise - linear_total_rise:+.4f} m"
    )

    # --- plot ---------------------------------------------------------------
    OUT_PLOT.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(11, 12))

    ax = axes[0]
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    ax.plot(
        df_val.index, df_val["sla_deseasonalized"], color="tab:gray", lw=0.8, alpha=0.7,
        label="deseasonalized SLA (val window)",
    )
    ax.plot(
        df_val.index, df_val["sla_ma12"], color="black", lw=1.2, alpha=0.8,
        label="12-mo MA of deseasonalized",
    )
    ax.plot(
        val_target_dates, actual_trend, color="tab:blue", lw=2.0,
        label="actual trend (val)",
    )
    ax.plot(
        val_target_dates, pred_trend, color="tab:red", lw=2.0,
        marker="o", ms=2.5,
        label=f"NN trend prediction (t+{HORIZON} mo)",
    )
    ax.plot(
        val_target_dates, lin_preds, color="tab:green", lw=1.2, ls="--",
        label=f"linear extrapolation of last {WINDOW} mo",
    )
    split_date = target_dates[split]
    ax.axvline(split_date, color="gray", ls="--", lw=0.8, label="train/val split")
    ax.set(
        ylabel="deseasonalized SLA trend (m)",
        title=(
            f"Trend forecast at t+{HORIZON} mo  |  wide-radius ({WIDE_RADIUS_DEG} deg) temp + MA anchor  |  "
            f"NN={rmse_nn:.4f}  persist={rmse_persist:.4f}  linear={rmse_lin:.4f}"
        ),
    )
    ax.legend(loc="best", fontsize=9)
    ax.set_xlim(plot_start, plot_end)

    ax = axes[1]
    with xr.open_dataset(SEA_NC) as ds:
        raw_msl = ds["msl"].to_series().sort_index()
    raw_msl_val = raw_msl.loc[plot_start:plot_end]
    ax.plot(
        raw_msl_val.index, raw_msl_val.values, color="tab:gray", lw=0.8, alpha=0.7,
        label="raw MSL (val window)",
    )
    ax.plot(
        val_target_dates, actual_msl, color="tab:blue", lw=1.6,
        label="actual MSL (val)",
    )
    ax.plot(
        val_target_dates, pred_msl, color="tab:red", lw=1.6,
        marker="o", ms=2.5,
        label="NN prediction + seasonal add-back",
    )
    ax.axvline(split_date, color="gray", ls="--", lw=0.8)
    ax.set(
        xlabel="Time", ylabel="MSL (m)",
        title="Validation window only: prediction re-applied to raw MSL via monthly climatology add-back",
    )
    ax.legend(loc="best", fontsize=9)
    ax.set_xlim(plot_start, plot_end)

    # Panel 3: autoregressive rollout, zoomed to 2000 + the rollout tail.
    ax = axes[2]
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    zoom_start = pd.Timestamp("2000-01-01")
    df_zoom = df.loc[zoom_start:]
    ax.plot(
        df_zoom.index, df_zoom["sla_ma12"], color="black", lw=1.4,
        label="12-mo MA trend (observed)",
    )
    ax.plot(
        df_zoom.index, df_zoom["sla_deseasonalized"], color="tab:gray", lw=0.5, alpha=0.35,
        label="deseasonalized SLA (observed)",
    )
    ax.plot(
        future_index, future_trend, color="tab:red", lw=2.0,
        label=f"NN+SLR rollout ({ROLLOUT_YEARS} yr)",
    )
    ax.plot(
        future_index, linear_future_trend, color="tab:green", lw=1.4, ls="--",
        label=f"linear-only rollout ({slr_rate * 1000:+.2f} mm/yr)",
    )
    ax.plot(
        future_index, future_msl, color="tab:orange", lw=1.0, alpha=0.6,
        label="NN+SLR rollout + detrended climatology",
    )
    ax.axvline(df.index[-1], color="gray", ls="--", lw=0.8, label="observation end")
    ax.set_xlim(zoom_start, future_index[-1])
    ax.set(
        xlabel="Time", ylabel="SLA (m)",
        title=(
            f"{ROLLOUT_YEARS}-year autoregressive forecast  |  NN rise={nn_total_rise:+.3f} m, "
            f"linear-only={linear_total_rise:+.3f} m, NN delta={nn_total_rise - linear_total_rise:+.3f} m"
        ),
    )
    ax.legend(loc="best", fontsize=9)

    fig.tight_layout()
    fig.savefig(OUT_PLOT, dpi=130)
    plt.close(fig)
    print(f"Chart written to {OUT_PLOT}")

    # --- CSV export ---------------------------------------------------------
    # Build a single monthly time-indexed frame covering observations + future.
    with xr.open_dataset(SEA_NC) as ds:
        raw_msl = ds["msl"].to_series().sort_index()
    raw_msl.index = pd.DatetimeIndex(raw_msl.index)

    full_index = pd.date_range(raw_msl.index.min(), future_index[-1], freq="MS")
    months = full_index.month
    seasonal = np.array([clim_by_month.loc[m] for m in months], dtype=np.float32)
    linear_abs = linear_trend_at(full_index, slr_rate, slr_intercept)

    out = pd.DataFrame(index=full_index)
    out.index.name = "time"
    out["observed_msl"] = raw_msl.reindex(full_index)
    out["observed_sla_deseasonalized"] = df["sla_deseasonalized"].reindex(full_index)
    out["observed_sla_ma12"] = df["sla_ma12"].reindex(full_index)
    out["seasonal_climatology"] = seasonal
    out["linear_trend_msl"] = linear_abs
    # Validation-period predictions: predicted trend + climatology at target date.
    pred_trend_series = pd.Series(pred_trend, index=val_target_dates)
    out["predicted_residual"] = pd.Series(pred_residual, index=val_target_dates).reindex(full_index)
    val_pred_trend_full = pred_trend_series.reindex(full_index)
    # Rollout (future period).
    future_series = pd.Series(future_trend, index=future_index)
    future_residual_series = pd.Series(future_residual, index=future_index)
    out["predicted_residual"] = out["predicted_residual"].combine_first(future_residual_series)
    # Combined predicted absolute trend (val + rollout).
    combined_trend = val_pred_trend_full.combine_first(future_series)
    out["predicted_trend"] = combined_trend
    out["predicted_msl"] = combined_trend + seasonal
    out["is_validation"] = out.index.isin(val_target_dates)
    out["is_future"] = out.index > df.index[-1]

    out.to_csv(OUT_CSV)
    print(f"CSV written to {OUT_CSV}  ({len(out)} rows, {out['predicted_msl'].notna().sum()} predicted months)")


if __name__ == "__main__":
    main()
