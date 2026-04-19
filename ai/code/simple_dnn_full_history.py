"""Dense NN for La Jolla SLA forecasting, full CalCOFI history (no Argo).

Same problem setup as simple_dnn.py but trained on the full 1949-2021 record
so the training window contains the 1982-83 and 1997-98 El Ninos. The
hypothesis: having comparable extreme events in training is more valuable
than adding Argo subsurface data only available for the last ~20 years.

Design:
- 3-month input window, 1-month lookahead
- features: temp_anomaly + rolling means, smoothed SLA
- target: 3-month rolling-mean SLA residual from the last observed smoothed SLA
- date-based split: train <2010, validate >=2010
- compared against persistence baseline
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch import nn

from compare_coops_calcofi_features import build_feature_table
from project_paths import PLOTS_DIR


WINDOW = 3
HORIZON = 1
TARGET_SMOOTH = 3
TRAIN_END = pd.Timestamp("2010-01-01")
HIDDEN = 16
EPOCHS = 800
LR = 3e-3
WEIGHT_DECAY = 1e-3
SEED = 0


def make_windows(
    features: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Residual target: y = target[t+1..t+H] - target[t_last]."""
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
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    df, _ = build_feature_table(radius_deg=1.5)
    df = df[["temp_anomaly", "sea_level_anomaly"]].dropna().sort_index()
    print(f"Monthly rows after dropna: {len(df)} ({df.index.min():%Y-%m} -> {df.index.max():%Y-%m})")

    df["sea_smooth"] = (
        df["sea_level_anomaly"].rolling(TARGET_SMOOTH, center=True, min_periods=TARGET_SMOOTH).mean()
    )
    df["temp_roll_6"] = df["temp_anomaly"].rolling(6, min_periods=6).mean()
    df["temp_roll_12"] = df["temp_anomaly"].rolling(12, min_periods=12).mean()
    df = df.dropna()
    print(f"Rows after smoothing: {len(df)} ({df.index.min():%Y-%m} -> {df.index.max():%Y-%m})")

    feature_cols = ["temp_anomaly", "temp_roll_6", "temp_roll_12", "sea_smooth"]
    features = df[feature_cols].to_numpy(dtype=np.float32)
    target = df["sea_smooth"].to_numpy(dtype=np.float32)
    sea_raw = df["sea_level_anomaly"].to_numpy(dtype=np.float32)

    x, y, anchor = make_windows(features, target)
    print(f"Windowed samples: {len(x)}  x-shape={x.shape}  y-shape={y.shape}")

    target_start_dates = df.index[WINDOW : WINDOW + len(x)]
    split = int((target_start_dates < TRAIN_END).sum())
    if split < 24 or split >= len(x):
        raise ValueError(
            f"Bad date split: {split} train / {len(x) - split} test "
            f"(TRAIN_END={TRAIN_END.date()})."
        )
    print(f"Train: {target_start_dates[0]:%Y-%m} -> {target_start_dates[split - 1]:%Y-%m} ({split} windows)")
    print(f"Val:   {target_start_dates[split]:%Y-%m} -> {target_start_dates[-1]:%Y-%m} ({len(x) - split} windows)")

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
            print(f"epoch {epoch:4d}  train_mse(norm)={loss.item():.4f}")

    model.eval()
    with torch.no_grad():
        pred_n = model(xv).cpu().numpy()
    pred_residual = pred_n * y_sd + y_mu
    pred = pred_residual + anchor_test[:, None]
    y_test_abs = y_test + anchor_test[:, None]

    rmse_per_step = np.sqrt(np.mean((pred - y_test_abs) ** 2, axis=0))
    mae_per_step = np.mean(np.abs(pred - y_test_abs), axis=0)
    rmse_overall = float(np.sqrt(np.mean((pred - y_test_abs) ** 2)))

    persistence = np.tile(anchor_test[:, None], (1, HORIZON))
    persistence_rmse = float(np.sqrt(np.mean((persistence - y_test_abs) ** 2)))
    mean_rmse = float(np.sqrt(np.mean((y_test_abs.mean(axis=0) - y_test_abs) ** 2)))

    print()
    print(f"Val samples: {len(y_test)}")
    for h in range(HORIZON):
        print(f"  t+{h + 1} month  RMSE={rmse_per_step[h]:.4f}  MAE={mae_per_step[h]:.4f}")
    print(f"Overall NN RMSE:          {rmse_overall:.4f}")
    print(f"Persistence baseline RMSE: {persistence_rmse:.4f}")
    print(f"Mean-predictor RMSE:       {mean_rmse:.4f}")

    # Continuous rolling prediction series (step = 1 when HORIZON=1).
    rolling_idx = list(range(0, len(y_test), HORIZON))
    rolling_pred: list[np.ndarray] = []
    rolling_actual: list[np.ndarray] = []
    rolling_times: list[pd.Timestamp] = []
    for i in rolling_idx:
        rolling_pred.append(pred[i])
        rolling_actual.append(y_test_abs[i])
        start = split + WINDOW + i
        rolling_times.extend(df.index[start : start + HORIZON])
    rolling_pred_arr = np.concatenate(rolling_pred)
    rolling_actual_arr = np.concatenate(rolling_actual)
    rolling_rmse = float(np.sqrt(np.mean((rolling_pred_arr - rolling_actual_arr) ** 2)))
    print(f"Rolling (step={HORIZON}) RMSE over val period: {rolling_rmse:.4f}")

    out_dir = PLOTS_DIR
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(df.index, sea_raw, color="black", lw=0.7, alpha=0.35, label="Actual raw SLA")
    ax.plot(df.index, target, color="black", lw=1.1, alpha=0.8, label="Actual 3-mo smooth SLA")
    ax.plot(rolling_times, rolling_actual_arr, color="tab:blue", lw=1.6, label="Actual smooth (val)")
    ax.plot(
        rolling_times, rolling_pred_arr, color="tab:red", lw=1.6, marker="o", ms=2.5,
        label=f"NN prediction (t+{HORIZON} mo)",
    )
    split_date = df.index[split + WINDOW]
    ax.axvline(split_date, color="gray", ls="--", lw=0.8, label="Train/val split")
    ax.set_xlabel("Time")
    ax.set_ylabel("Sea level anomaly (m)")
    ax.set_title(
        f"Full-history model (no Argo)  |  NN={rolling_rmse:.4f}  persistence={persistence_rmse:.4f}  "
        f"|  train<{TRAIN_END.year}, val>={TRAIN_END.year}"
    )
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    out_path = out_dir / "simple_dnn_full_history.png"
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"Chart written to {out_path}")


if __name__ == "__main__":
    main()
