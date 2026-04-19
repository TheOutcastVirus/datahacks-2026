"""Stochastic-forcing variant of the SLA residual NN forecaster.

Identical feature stack to `simple_dnn_full_history_wide_projection.py`, but the
final layer outputs `(mu, log_sigma)` per sample and trains with Gaussian NLL.
At inference we sample from the predicted distribution at every rollout step,
which prevents the deterministic fixed-point collapse (residual std -> 0 after
~2032). Running 200 Monte-Carlo rollouts gives an uncertainty fan.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import xarray as xr
from torch import nn

from project_paths import PLOTS_DIR, SLA_PREDICTION_STOCHASTIC_CSV

from simple_dnn_full_history_wide_projection import (  # noqa: E402
    build_feature_frame,
    linear_trend_at,
    WINDOW,
    HORIZON,
    TRAIN_END,
    ROLLOUT_YEARS,
    WIDE_RADIUS_DEG,
    SEA_NC,
)


HIDDEN = 32
EPOCHS = 2000
LR = 3e-3
WEIGHT_DECAY = 1e-3
SEED = 0

N_SAMPLES = 200
LOG_SIGMA_MIN = -6.0
LOG_SIGMA_MAX = 2.0

OUT_PLOT = PLOTS_DIR / "simple_dnn_stochastic.png"
OUT_CSV = SLA_PREDICTION_STOCHASTIC_CSV


# ---- model ------------------------------------------------------------------


class StochasticDenseNet(nn.Module):
    def __init__(self, in_dim: int, hidden: int = HIDDEN):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        self.head_mu = nn.Linear(hidden, 1)
        self.head_log_sigma = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.trunk(x)
        mu = self.head_mu(h)
        log_sigma = torch.clamp(self.head_log_sigma(h), LOG_SIGMA_MIN, LOG_SIGMA_MAX)
        return mu, log_sigma


def gaussian_nll(mu: torch.Tensor, log_sigma: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    # 0.5 * (log(2*pi) + 2*log_sigma + ((y - mu)/exp(log_sigma))**2)
    inv_var = torch.exp(-2.0 * log_sigma)
    return 0.5 * (np.log(2.0 * np.pi) + 2.0 * log_sigma + (y - mu) ** 2 * inv_var).mean()


# ---- windowing --------------------------------------------------------------


def make_windows(features: np.ndarray, trend: np.ndarray):
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


# ---- stochastic rollout -----------------------------------------------------


def stochastic_rollout(
    model: nn.Module,
    device: str,
    df: pd.DataFrame,
    feature_cols: list[str],
    x_mu: np.ndarray,
    x_sd: np.ndarray,
    y_mu: np.ndarray,
    y_sd: np.ndarray,
    years: int,
    n_samples: int,
    seed: int = 0,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Return (future_index, ensemble) with ensemble shape (n_samples, n_months)."""
    last_date = df.index[-1]
    steps = int(np.ceil(years * 12 / HORIZON))
    future_end = last_date + pd.DateOffset(months=steps * HORIZON)
    future_index = pd.date_range(
        start=last_date + pd.DateOffset(months=1),
        end=future_end,
        freq="MS",
    )

    if feature_cols != [
        "sla_ma12_detrended", "temp_wide_anomaly", "temp_wide_roll_6", "temp_wide_roll_12"
    ]:
        raise RuntimeError("Feature order hard-coded in rollout; update here if you change it.")

    hist_resid = df["sla_ma12_detrended"].astype(np.float32).to_numpy()
    hist_index = df.index
    temp_anom_vals = df["temp_wide_anomaly"].astype(np.float32).to_numpy()
    temp_r6_vals = df["temp_wide_roll_6"].astype(np.float32).to_numpy()
    temp_r12_vals = df["temp_wide_roll_12"].astype(np.float32).to_numpy()

    n_future = len(future_index)
    ensemble = np.empty((n_samples, n_future), dtype=np.float32)

    model.eval()
    rng = np.random.default_rng(seed)

    for s in range(n_samples):
        # Build the mutable residual series: historical + nan placeholders.
        resid = np.concatenate([hist_resid, np.full(n_future, np.nan, dtype=np.float32)])
        # Corresponding temperature-feature series. Future values = 0 (climatology).
        temp_a = np.concatenate([temp_anom_vals, np.zeros(n_future, dtype=np.float32)])
        temp_6 = np.concatenate([temp_r6_vals, np.zeros(n_future, dtype=np.float32)])
        temp_12 = np.concatenate([temp_r12_vals, np.zeros(n_future, dtype=np.float32)])

        hist_len = len(hist_resid)
        for step in range(steps):
            # anchor index in the combined series
            anchor_idx = hist_len - 1 + step * HORIZON
            window_slice = slice(anchor_idx - WINDOW + 1, anchor_idx + 1)
            sla_w = resid[window_slice]
            ta_w = temp_a[window_slice]
            t6_w = temp_6[window_slice]
            t12_w = temp_12[window_slice]

            feat = np.stack([sla_w, ta_w, t6_w, t12_w], axis=1).reshape(-1)
            x_n = (feat - x_mu) / x_sd
            with torch.no_grad():
                mu_n, log_sigma_n = model(
                    torch.from_numpy(x_n[None, :]).to(device)
                )
            mu_n_val = float(mu_n.cpu().numpy().reshape(-1)[0])
            sigma_n_val = float(np.exp(log_sigma_n.cpu().numpy().reshape(-1)[0]))
            z = float(rng.standard_normal())
            delta_n = mu_n_val + sigma_n_val * z
            # denormalise
            delta = delta_n * float(y_sd[0]) + float(y_mu[0])

            anchor_val = float(sla_w[-1])
            new_val = anchor_val + delta
            # linear interpolate HORIZON months between anchor and new_val
            interp = np.linspace(anchor_val, new_val, HORIZON + 1, dtype=np.float32)[1:]
            fill_start = anchor_idx + 1
            resid[fill_start : fill_start + HORIZON] = interp

        ensemble[s] = resid[hist_len:]

    return future_index, ensemble


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
    print(f"Windowed samples: {len(x)}  x-shape={x.shape}  y-shape={y.shape}")

    target_dates = df.index[WINDOW + HORIZON - 1 : WINDOW + HORIZON - 1 + len(x)]
    split = int((target_dates < TRAIN_END).sum())
    print(f"Train: {split} windows, Val: {len(x) - split} windows")

    x_train, x_val = x[:split], x[split:]
    y_train, y_val = y[:split], y[split:]
    anchor_train, anchor_val_arr = anchor[:split], anchor[split:]
    val_target_dates = target_dates[split:]

    x_mu = x_train.mean(axis=0)
    x_sd = x_train.std(axis=0)
    x_sd[x_sd == 0] = 1.0
    y_mu = y_train.mean(axis=0)
    y_sd = y_train.std(axis=0)
    y_sd[y_sd == 0] = 1.0

    x_train_n = (x_train - x_mu) / x_sd
    x_val_n = (x_val - x_mu) / x_sd
    y_train_n = (y_train - y_mu) / y_sd

    train_residual_std = float(np.std(y_train))
    print(f"Train residual-delta std (raw): {train_residual_std:.4f}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = StochasticDenseNet(in_dim=x.shape[1]).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

    xt = torch.from_numpy(x_train_n).to(device)
    yt = torch.from_numpy(y_train_n).to(device)
    xv = torch.from_numpy(x_val_n).to(device)

    for epoch in range(1, EPOCHS + 1):
        model.train()
        opt.zero_grad()
        mu_t, log_sigma_t = model(xt)
        loss = gaussian_nll(mu_t, log_sigma_t, yt)
        loss.backward()
        opt.step()
        if epoch % 200 == 0 or epoch == 1:
            with torch.no_grad():
                sigma_mean = torch.exp(log_sigma_t).mean().item() * float(y_sd[0])
                mse_mu = ((mu_t - yt) ** 2).mean().item()
            print(
                f"epoch {epoch:4d}  nll={loss.item():+.4f}  "
                f"mse_mu(norm)={mse_mu:.4f}  avg_sigma(raw)={sigma_mean:.4f}"
            )

    model.eval()
    with torch.no_grad():
        mu_v_n, log_sigma_v_n = model(xv)
    mu_v_n = mu_v_n.cpu().numpy().reshape(-1)
    sigma_v_n = np.exp(log_sigma_v_n.cpu().numpy().reshape(-1))

    # denormalise
    pred_delta = mu_v_n * float(y_sd[0]) + float(y_mu[0])
    pred_sigma = sigma_v_n * float(y_sd[0])
    actual_delta = y_val.reshape(-1)

    # Trend-level reconstruction for RMSE reporting.
    linear_at_val = linear_trend_at(val_target_dates, slr_rate, slr_intercept)
    pred_residual_val = anchor_val_arr + pred_delta
    actual_residual_val = anchor_val_arr + actual_delta
    pred_trend_val = pred_residual_val + linear_at_val
    actual_trend_val = actual_residual_val + linear_at_val

    rmse_mu_trend = float(np.sqrt(np.mean((pred_trend_val - actual_trend_val) ** 2)))

    # Train RMSE on mu only.
    with torch.no_grad():
        mu_tr_n, _ = model(xt)
    mu_tr = mu_tr_n.cpu().numpy().reshape(-1) * float(y_sd[0]) + float(y_mu[0])
    rmse_mu_train_delta = float(np.sqrt(np.mean((mu_tr - y_train.reshape(-1)) ** 2)))
    rmse_mu_val_delta = float(np.sqrt(np.mean((pred_delta - actual_delta) ** 2)))

    # 90% coverage on residual delta: actual within mu +/- 1.645 * sigma.
    z90 = 1.6448536269514722
    lo = pred_delta - z90 * pred_sigma
    hi = pred_delta + z90 * pred_sigma
    coverage_90 = float(np.mean((actual_delta >= lo) & (actual_delta <= hi)))
    avg_sigma_val = float(np.mean(pred_sigma))

    print()
    print(f"Train RMSE of mu on residual-delta:     {rmse_mu_train_delta:.4f}")
    print(f"Val   RMSE of mu on residual-delta:     {rmse_mu_val_delta:.4f}")
    print(f"Val   RMSE of mu on absolute trend:     {rmse_mu_trend:.4f}  (det. baseline 0.0517)")
    print(f"Val   avg predicted sigma (raw units):  {avg_sigma_val:.4f}")
    print(f"Val   90% coverage:                     {coverage_90:.3f}  (target 0.80-0.95)")

    # --- rollout ------------------------------------------------------------
    future_index, ensemble_resid = stochastic_rollout(
        model, device, df, feature_cols,
        x_mu, x_sd, y_mu, y_sd,
        years=ROLLOUT_YEARS,
        n_samples=N_SAMPLES,
        seed=SEED,
    )
    linear_at_future = linear_trend_at(future_index, slr_rate, slr_intercept)
    ensemble_trend = ensemble_resid + linear_at_future[None, :]

    future_months = future_index.month
    future_seasonal = np.array(
        [clim_by_month.loc[m] for m in future_months], dtype=np.float32
    )
    ensemble_msl = ensemble_trend + future_seasonal[None, :]

    med = np.median(ensemble_msl, axis=0)
    p05 = np.percentile(ensemble_msl, 5, axis=0)
    p25 = np.percentile(ensemble_msl, 25, axis=0)
    p75 = np.percentile(ensemble_msl, 75, axis=0)
    p95 = np.percentile(ensemble_msl, 95, axis=0)

    trend_med = np.median(ensemble_trend, axis=0)
    trend_p05 = np.percentile(ensemble_trend, 5, axis=0)
    trend_p25 = np.percentile(ensemble_trend, 25, axis=0)
    trend_p75 = np.percentile(ensemble_trend, 75, axis=0)
    trend_p95 = np.percentile(ensemble_trend, 95, axis=0)

    # Residual-std by 5-year block across the ensemble.
    print()
    print("Rollout residual std by 5-year block (median across samples):")
    years_from_start = (future_index.year - future_index[0].year) + (
        future_index.month - future_index[0].month
    ) / 12.0
    all_block_stds = []
    block_starts = np.arange(0, ROLLOUT_YEARS, 5)
    for bs in block_starts:
        mask = (years_from_start >= bs) & (years_from_start < bs + 5)
        if not mask.any():
            continue
        # std of each ensemble member's residual within block, then median
        block = ensemble_resid[:, mask]
        per_sample_std = block.std(axis=1)
        med_std = float(np.median(per_sample_std))
        all_block_stds.append(med_std)
        yr0 = future_index[0].year + bs
        print(f"  {yr0}-{yr0 + 5}: median sample std = {med_std:.4f}")
    min_block_std = float(min(all_block_stds))
    print(f"Min 5-year block residual std: {min_block_std:.4f}  (must be > 0.005)")

    last_trend = float(df["sla_ma12"].iloc[-1])
    final_rise_med = float(trend_med[-1] - last_trend)
    final_rise_p05 = float(trend_p05[-1] - last_trend)
    final_rise_p95 = float(trend_p95[-1] - last_trend)
    print()
    print(f"Final MSL rise over {ROLLOUT_YEARS} yr  median: {final_rise_med:+.4f} m")
    print(f"                               5-95%: [{final_rise_p05:+.4f}, {final_rise_p95:+.4f}] m")

    # --- static plot --------------------------------------------------------
    OUT_PLOT.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(11, 12))

    plot_start = val_target_dates.min()
    plot_end = val_target_dates.max()
    df_val = df.loc[plot_start:plot_end]

    # Validation window predictions with band (mu +/- 1.645 sigma).
    val_trend_med = pred_trend_val
    val_trend_lo = (anchor_val_arr + (pred_delta - z90 * pred_sigma)) + linear_at_val
    val_trend_hi = (anchor_val_arr + (pred_delta + z90 * pred_sigma)) + linear_at_val

    ax = axes[0]
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    ax.plot(df_val.index, df_val["sla_deseasonalized"], color="tab:gray", lw=0.8, alpha=0.7,
            label="deseasonalized SLA (val)")
    ax.plot(df_val.index, df_val["sla_ma12"], color="black", lw=1.2, alpha=0.8,
            label="12-mo MA")
    ax.plot(val_target_dates, actual_trend_val, color="tab:blue", lw=2.0, label="actual trend")
    ax.plot(val_target_dates, val_trend_med, color="tab:red", lw=2.0, label="median prediction")
    ax.fill_between(val_target_dates, val_trend_lo, val_trend_hi,
                    color="tab:red", alpha=0.2, label="90% band (mu +/- 1.645 sigma)")
    ax.set(ylabel="deseasonalized SLA trend (m)",
           title=f"Validation window (coverage {coverage_90:.2f}, avg sigma {avg_sigma_val:.4f})")
    ax.legend(loc="best", fontsize=9)
    ax.set_xlim(plot_start, plot_end)

    ax = axes[1]
    with xr.open_dataset(SEA_NC) as ds:
        raw_msl = ds["msl"].to_series().sort_index()
    raw_msl_val = raw_msl.loc[plot_start:plot_end]
    val_months = val_target_dates.month
    seasonal_val = np.array([clim_by_month.loc[m] for m in val_months], dtype=np.float32)
    val_msl_med = val_trend_med + seasonal_val
    val_msl_lo = val_trend_lo + seasonal_val
    val_msl_hi = val_trend_hi + seasonal_val
    ax.plot(raw_msl_val.index, raw_msl_val.values, color="tab:gray", lw=0.8, alpha=0.7,
            label="raw MSL (val)")
    ax.plot(val_target_dates, actual_trend_val + seasonal_val, color="tab:blue", lw=1.6,
            label="actual MSL")
    ax.plot(val_target_dates, val_msl_med, color="tab:red", lw=1.6, label="median MSL pred")
    ax.fill_between(val_target_dates, val_msl_lo, val_msl_hi, color="tab:red", alpha=0.2,
                    label="90% band")
    ax.set(ylabel="MSL (m)", title="Validation-window MSL with uncertainty band")
    ax.legend(loc="best", fontsize=9)
    ax.set_xlim(plot_start, plot_end)

    ax = axes[2]
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    zoom_start = pd.Timestamp("2000-01-01")
    df_zoom = df.loc[zoom_start:]
    ax.plot(df_zoom.index, df_zoom["sla_ma12"], color="black", lw=1.4,
            label="12-mo MA (observed)")
    ax.plot(df_zoom.index, df_zoom["sla_deseasonalized"], color="tab:gray", lw=0.5, alpha=0.35,
            label="deseasonalized SLA (observed)")
    ax.fill_between(future_index, trend_p05, trend_p95, color="tab:red", alpha=0.18,
                    label="5-95% band")
    ax.fill_between(future_index, trend_p25, trend_p75, color="tab:red", alpha=0.35,
                    label="25-75% band")
    ax.plot(future_index, trend_med, color="tab:red", lw=1.8, label="median rollout")
    ax.plot(future_index, linear_at_future, color="tab:green", lw=1.4, ls="--",
            label=f"linear-only ({slr_rate * 1000:+.2f} mm/yr)")
    ax.axvline(df.index[-1], color="gray", ls="--", lw=0.8, label="obs end")
    ax.set_xlim(zoom_start, future_index[-1])
    ax.set(xlabel="Time", ylabel="SLA trend (m)",
           title=(
               f"{ROLLOUT_YEARS}-yr stochastic rollout ({N_SAMPLES} samples)  |  "
               f"final rise median {final_rise_med:+.3f} m, "
               f"5-95% [{final_rise_p05:+.3f}, {final_rise_p95:+.3f}] m"
           ))
    ax.legend(loc="best", fontsize=9)

    fig.tight_layout()
    fig.savefig(OUT_PLOT, dpi=130)
    plt.close(fig)
    print(f"Chart written to {OUT_PLOT}")

    # --- CSV export ---------------------------------------------------------
    with xr.open_dataset(SEA_NC) as ds:
        raw_msl = ds["msl"].to_series().sort_index()
    raw_msl.index = pd.DatetimeIndex(raw_msl.index)

    full_index = pd.date_range(raw_msl.index.min(), future_index[-1], freq="MS")
    months = full_index.month
    seasonal_full = np.array([clim_by_month.loc[m] for m in months], dtype=np.float32)
    linear_abs_full = linear_trend_at(full_index, slr_rate, slr_intercept)

    # Future series aligned to full_index.
    def _reindex(arr: np.ndarray) -> pd.Series:
        return pd.Series(arr, index=future_index).reindex(full_index)

    out = pd.DataFrame(index=full_index)
    out.index.name = "time"
    out["observed_msl"] = raw_msl.reindex(full_index)
    out["seasonal_climatology"] = seasonal_full
    out["linear_trend_msl"] = linear_abs_full
    out["pred_msl_median"] = _reindex(med)
    out["pred_msl_p05"] = _reindex(p05)
    out["pred_msl_p25"] = _reindex(p25)
    out["pred_msl_p75"] = _reindex(p75)
    out["pred_msl_p95"] = _reindex(p95)
    out["pred_trend_median"] = _reindex(trend_med)
    out["pred_trend_p05"] = _reindex(trend_p05)
    out["pred_trend_p25"] = _reindex(trend_p25)
    out["pred_trend_p75"] = _reindex(trend_p75)
    out["pred_trend_p95"] = _reindex(trend_p95)
    out["observed_sla_deseasonalized"] = df["sla_deseasonalized"].reindex(full_index)
    out["observed_sla_ma12"] = df["sla_ma12"].reindex(full_index)
    out["is_future"] = out.index > df.index[-1]

    out.to_csv(OUT_CSV)
    print(f"CSV written to {OUT_CSV}  ({len(out)} rows)")

    # --- Acceptance checks --------------------------------------------------
    print()
    print("=== Acceptance criteria ===")
    ok_cov = 0.80 <= coverage_90 <= 0.95
    ok_std = min_block_std > 0.005
    print(f"  val 90% coverage in [0.80, 0.95]:        {ok_cov}  ({coverage_90:.3f})")
    print(f"  min 5-yr block residual std > 0.005:     {ok_std}  ({min_block_std:.4f})")


if __name__ == "__main__":
    main()
