"""Dense NN with a CalCOFI-based basin-scale heat proxy spanning 1949-2021.

Option B: the full-history model (no Argo) extended with a depth-integrated
CalCOFI temperature feature computed over a broader offshore box. The proxy
behaves like Argo's 0-700 dbar heat content but covers the full 70+ year
record, so the 1997-98 and 1982-83 El Ninos stay in the training window.

Run once from a kernel or a shell. Writes outputs/plots/simple_dnn_calcofi_heat.png.
"""
from __future__ import annotations

from time import perf_counter

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import xarray as xr
from torch import nn

from compare_coops_calcofi_features import build_feature_table
from project_paths import PLOTS_DIR, PROCESSED_CALCOFI_NC


WINDOW = 3
HORIZON = 1
TARGET_SMOOTH = 3
TRAIN_END = pd.Timestamp("2010-01-01")
HIDDEN = 16
EPOCHS = 800
LR = 3e-3
WEIGHT_DECAY = 1e-3
SEED = 0

# Broader box than the 1.5-deg nearshore one used in compare_coops_calcofi_features.
# Target basin-scale thermal variability of the California Current offshore of SoCal.
BOX_LAT = (29.0, 36.0)
BOX_LON = (-125.0, -117.0)
INTEGRATION_DEPTH_M = 500.0
MIN_REACH_M = 300.0  # only use profiles that reach at least this deep
MIN_TOP_M = 20.0     # and start shallow enough

CALCOFI_NC = PROCESSED_CALCOFI_NC


def log(message: str, start: float | None = None) -> None:
    if start is None:
        print(message, flush=True)
        return
    print(f"[+{perf_counter() - start:6.2f}s] {message}", flush=True)


def build_calcofi_heat(calcofi_nc: Path = CALCOFI_NC) -> pd.Series:
    """Depth-integrate CalCOFI temperature over 0-500 m for a broad offshore box.

    Returns monthly climatology-removed heat anomaly (degC*m).
    """
    started = perf_counter()
    log(f"Opening CalCOFI heat dataset: {calcofi_nc.name}", started)
    with xr.open_dataset(calcofi_nc, engine="netcdf4") as ds:
        box = (
            (ds.lat >= BOX_LAT[0]) & (ds.lat <= BOX_LAT[1])
            & (ds.lon >= BOX_LON[0]) & (ds.lon <= BOX_LON[1])
        ).values
        sub = ds.isel(profile=box)
        log(
            f"Selected {int(box.sum())} profiles in box "
            f"{BOX_LAT[0]:.1f}-{BOX_LAT[1]:.1f}N, {BOX_LON[0]:.1f}-{BOX_LON[1]:.1f}E",
            started,
        )
        # Slice to the integration range before materializing the array. Loading the
        # full 0-5351 m matrix makes startup look hung because it pulls ~6x more data
        # than the 0-500 m integral actually needs.
        temp_view = sub.Temp.sel(depth=slice(0, INTEGRATION_DEPTH_M))
        depth = temp_view.depth.values.astype(np.float64)
        temp = temp_view.values.astype(np.float64)  # (profile, depth<=500 m)
        times = pd.to_datetime(sub.time.values)
        log(
            f"Loaded temperature matrix with shape {temp.shape} for heat integration",
            started,
        )

    trapz = getattr(np, "trapezoid", None) or np.trapz
    depth_sub = depth
    temp_sub = temp

    heat = np.full(temp_sub.shape[0], np.nan, dtype=np.float64)
    log("Integrating profile heat content to 500 m", started)
    for i in range(temp_sub.shape[0]):
        t = temp_sub[i]
        valid = np.isfinite(t)
        if valid.sum() < 4:
            continue
        p = depth_sub[valid]
        tv = t[valid]
        if p[0] > MIN_TOP_M or p[-1] < MIN_REACH_M:
            continue
        heat[i] = trapz(tv, p)
        if (i + 1) % 5000 == 0:
            log(f"Integrated {i + 1}/{temp_sub.shape[0]} profiles", started)

    df = pd.DataFrame({"time": times, "heat": heat}).dropna()
    log(f"Integrated heat for {len(df)} valid profiles; aggregating monthly", started)
    monthly = df.set_index("time")["heat"].resample("MS").mean()
    monthly.index.name = "time"
    clim = monthly.groupby(monthly.index.month).transform("mean")
    anomaly = monthly - clim
    anomaly.name = "calcofi_heat_anomaly"
    log(f"Built monthly CalCOFI heat anomaly series with {len(anomaly)} rows", started)
    return anomaly


def make_windows(
    features: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, y, anchor = [], [], []
    n = len(target)
    for i in range(n - WINDOW - HORIZON + 1):
        feat_window = features[i : i + WINDOW]
        target_window = target[i + WINDOW : i + WINDOW + HORIZON]
        last = target[i + WINDOW - 1]
        if (
            np.isfinite(feat_window).all()
            and np.isfinite(target_window).all()
            and np.isfinite(last)
        ):
            x.append(feat_window.reshape(-1))
            y.append(target_window - last)
            anchor.append(last)
    return (
        np.asarray(x, dtype=np.float32),
        np.asarray(y, dtype=np.float32),
        np.asarray(anchor, dtype=np.float32),
    )


class DenseNet(nn.Module):
    def __init__(self, in_dim: int, out_dim: int, hidden: int = HIDDEN):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def main() -> None:
    started = perf_counter()
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    log("Building base feature table from CO-OPS + nearby CalCOFI", started)
    df, _ = build_feature_table(radius_deg=1.5)
    df = df[["temp_anomaly", "sea_level_anomaly"]].dropna().sort_index()
    log(
        f"Monthly rows from feature table: {len(df)} "
        f"({df.index.min():%Y-%m} -> {df.index.max():%Y-%m})",
        started,
    )

    log("Building basin-scale CalCOFI heat proxy", started)
    heat = build_calcofi_heat()
    log(
        f"CalCOFI basin heat proxy: {len(heat)} months "
        f"({heat.index.min():%Y-%m} -> {heat.index.max():%Y-%m}), "
        f"non-null = {heat.notna().sum()}",
        started,
    )
    heat_smooth = heat.rolling(3, min_periods=3).mean().rename("calcofi_heat_smooth")

    df = df.join(heat).join(heat_smooth)
    df["sea_smooth"] = (
        df["sea_level_anomaly"].rolling(TARGET_SMOOTH, center=True, min_periods=TARGET_SMOOTH).mean()
    )
    df["temp_roll_6"] = df["temp_anomaly"].rolling(6, min_periods=6).mean()
    df["temp_roll_12"] = df["temp_anomaly"].rolling(12, min_periods=12).mean()
    df = df.dropna()
    log(
        f"Rows after smoothing + heat join: {len(df)} "
        f"({df.index.min():%Y-%m} -> {df.index.max():%Y-%m})",
        started,
    )

    feature_cols = [
        "temp_anomaly",
        "temp_roll_6",
        "temp_roll_12",
        "sea_smooth",
        "calcofi_heat_anomaly",
        "calcofi_heat_smooth",
    ]
    features = df[feature_cols].to_numpy(dtype=np.float32)
    target = df["sea_smooth"].to_numpy(dtype=np.float32)
    sea_raw = df["sea_level_anomaly"].to_numpy(dtype=np.float32)

    x, y, anchor = make_windows(features, target)
    log(f"Windowed samples: {len(x)}  x-shape={x.shape}  y-shape={y.shape}", started)

    target_start_dates = df.index[WINDOW : WINDOW + len(x)]
    split = int((target_start_dates < TRAIN_END).sum())
    if split < 24 or split >= len(x):
        raise ValueError(
            f"Bad date split: {split} train / {len(x) - split} test "
            f"(TRAIN_END={TRAIN_END.date()})."
        )
    log(
        f"Train: {target_start_dates[0]:%Y-%m} -> {target_start_dates[split - 1]:%Y-%m} "
        f"({split} windows)",
        started,
    )
    log(
        f"Val:   {target_start_dates[split]:%Y-%m} -> {target_start_dates[-1]:%Y-%m} "
        f"({len(x) - split} windows)",
        started,
    )

    x_train, x_test = x[:split], x[split:]
    y_train, y_test = y[:split], y[split:]
    anchor_train, anchor_test = anchor[:split], anchor[split:]

    x_mu, x_sd = x_train.mean(axis=0), x_train.std(axis=0)
    x_sd[x_sd == 0] = 1.0
    y_mu, y_sd = y_train.mean(axis=0), y_train.std(axis=0)
    y_sd[y_sd == 0] = 1.0

    x_train_n = (x_train - x_mu) / x_sd
    x_test_n = (x_test - x_mu) / x_sd
    y_train_n = (y_train - y_mu) / y_sd

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"Training DenseNet on device={device}", started)
    model = DenseNet(in_dim=x.shape[1], out_dim=HORIZON).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    loss_fn = nn.MSELoss()

    xt = torch.from_numpy(x_train_n).to(device)
    yt = torch.from_numpy(y_train_n).to(device)
    xv = torch.from_numpy(x_test_n).to(device)

    for epoch in range(1, EPOCHS + 1):
        model.train()
        opt.zero_grad()
        pred = model(xt)
        loss = loss_fn(pred, yt)
        loss.backward()
        opt.step()
        if epoch % 50 == 0 or epoch == 1:
            log(f"epoch {epoch:4d}  train_mse(norm)={loss.item():.4f}", started)

    model.eval()
    with torch.no_grad():
        pred_n = model(xv).cpu().numpy()
    pred = pred_n * y_sd + y_mu + anchor_test[:, None]
    y_test_abs = y_test + anchor_test[:, None]

    rmse_per_step = np.sqrt(np.mean((pred - y_test_abs) ** 2, axis=0))
    mae_per_step = np.mean(np.abs(pred - y_test_abs), axis=0)
    rmse_overall = float(np.sqrt(np.mean((pred - y_test_abs) ** 2)))
    persistence = np.tile(anchor_test[:, None], (1, HORIZON))
    persistence_rmse = float(np.sqrt(np.mean((persistence - y_test_abs) ** 2)))
    mean_rmse = float(np.sqrt(np.mean((y_test_abs.mean(axis=0) - y_test_abs) ** 2)))

    print(flush=True)
    log(f"Val samples: {len(y_test)}", started)
    for h in range(HORIZON):
        log(f"  t+{h + 1} month  RMSE={rmse_per_step[h]:.4f}  MAE={mae_per_step[h]:.4f}", started)
    log(f"Overall NN RMSE:          {rmse_overall:.4f}", started)
    log(f"Persistence baseline RMSE: {persistence_rmse:.4f}", started)
    log(f"Mean-predictor RMSE:       {mean_rmse:.4f}", started)

    rolling_pred = []
    rolling_actual = []
    rolling_times: list[pd.Timestamp] = []
    for i in range(0, len(y_test), HORIZON):
        rolling_pred.append(pred[i])
        rolling_actual.append(y_test_abs[i])
        start = split + WINDOW + i
        rolling_times.extend(df.index[start : start + HORIZON])
    rolling_pred_arr = np.concatenate(rolling_pred)
    rolling_actual_arr = np.concatenate(rolling_actual)
    rolling_rmse = float(np.sqrt(np.mean((rolling_pred_arr - rolling_actual_arr) ** 2)))
    log(f"Rolling (step={HORIZON}) RMSE over val period: {rolling_rmse:.4f}", started)

    out_dir = PLOTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(df.index, sea_raw, color="black", lw=0.7, alpha=0.35, label="Actual raw SLA")
    ax.plot(df.index, target, color="black", lw=1.1, alpha=0.8, label="Actual 3-mo smooth SLA")
    ax.plot(
        rolling_times, rolling_actual_arr, color="tab:blue", lw=1.6, label="Actual smooth (val)"
    )
    ax.plot(
        rolling_times, rolling_pred_arr, color="tab:red", lw=1.6, marker="o", ms=2.5,
        label=f"NN prediction (t+{HORIZON} mo)",
    )
    split_date = df.index[split + WINDOW]
    ax.axvline(split_date, color="gray", ls="--", lw=0.8, label="Train/val split")
    ax.set_xlabel("Time")
    ax.set_ylabel("Sea level anomaly (m)")
    ax.set_title(
        f"Full-history + CalCOFI heat proxy  |  NN={rolling_rmse:.4f}  "
        f"persistence={persistence_rmse:.4f}  |  train<{TRAIN_END.year}, val>={TRAIN_END.year}"
    )
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    out_path = out_dir / "simple_dnn_calcofi_heat.png"
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    log(f"Chart written to {out_path}", started)


if __name__ == "__main__":
    main()
