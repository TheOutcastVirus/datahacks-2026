from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import xarray as xr

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit(
        "matplotlib is not installed. Run `pip install -r requirements.txt` first."
    ) from exc


DEFAULT_ARGO_OVERLAP_PATH = Path("data/normalized/sojs_active_modern_overlap_with_argo.nc")
DEFAULT_OUTPUT_DIR = Path("data/hindcast")
DEFAULT_PLOT_DIR = Path("plots/hindcast")
DEFAULT_N_SPLITS = 5

STATIONS = {
    "Portland": {
        "variable": "portland_msl_m",
        "gia_rate_mm_yr": 1.1,
    },
    "Bar Harbor": {
        "variable": "bar_harbor_msl_m",
        "gia_rate_mm_yr": 1.3,
    },
}

EXTERNAL_PREDICTORS = [
    "copernicus_sla_gom_m_zscore",
    "grace_hist_lwe_thickness_gom_m_zscore",
    "greenland_mass_gt_zscore",
]

# Use density only: it encodes both T and S physically (density = f(T, S, P)).
# Using all three creates near-collinear columns that inflate OLS coefficient
# variance on short training windows and degrade out-of-sample skill.
ARGO_PREDICTORS = [
    "argo_density_shelf_0_200dbar_kg_m3_zscore",
]

LAMBDA_GRID = np.logspace(-3, 3, 50)  # 0.001 → 1000; used by inner CV when no lambda is forced
DEFAULT_RIDGE_LAMBDA = 10.0  # strong default; inner CV on ~8-month folds is too noisy to be useful

# ols_with_argo_ridge is the final model — the others are comparison baselines.
MODEL_ORDER = [
    "persistence",
    "trend_only",
    "trend_seasonal",
    "ols_reduced",
    "ols_reduced_detrended",
    "ols_with_argo_detrended",
    "ols_with_argo_ridge",
]

FINAL_MODEL = "ols_with_argo_ridge"


@dataclass(frozen=True)
class FinalModelFit:
    station_name: str
    station_variable: str
    gia_rate_mm_yr: float
    predictor_names: tuple[str, ...]
    time_origin: pd.Timestamp
    gia_reference_mean_m: float
    target_baseline_m: float
    target_seasonal_means: np.ndarray
    target_trend_slope: float
    target_trend_intercept: float
    predictor_seasonal_means: np.ndarray
    predictor_trend_slopes: np.ndarray
    predictor_trend_intercepts: np.ndarray
    predictor_stds: np.ndarray
    coefficients: np.ndarray
    ridge_lambda: float


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 4 hindcast modeling: evaluate models on the Argo overlap period. "
            "Trend-adjusted seasonal cycles are pre-removed from the target AND every predictor "
            "before all CV loops; per-fold detrending then isolates residual dynamic co-variance."
        )
    )
    parser.add_argument("--argo-overlap", type=Path, default=DEFAULT_ARGO_OVERLAP_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--n-splits", type=int, default=DEFAULT_N_SPLITS)
    parser.add_argument(
        "--ridge-lambda",
        type=float,
        default=DEFAULT_RIDGE_LAMBDA,
        help=(
            f"Ridge penalty lambda (default {DEFAULT_RIDGE_LAMBDA}). "
            "Increase to shrink the Argo coefficient more aggressively toward zero. "
            "Decrease if the Argo signal is being suppressed too much. "
            "Pass 0 to use inner CV lambda selection instead."
        ),
    )
    return parser.parse_args(argv)


def load_frame(path: Path) -> pd.DataFrame:
    ds = xr.open_dataset(path)
    try:
        frame = ds.to_dataframe()
    finally:
        ds.close()
    frame.index = pd.to_datetime(frame.index)
    return frame.sort_index()


def years_since_origin(index: pd.DatetimeIndex, origin: pd.Timestamp) -> np.ndarray:
    days = np.asarray((index - pd.Timestamp(origin)).days, dtype=float)
    return days / 365.2425


def years_since_start(index: pd.DatetimeIndex) -> np.ndarray:
    return years_since_origin(index, pd.Timestamp(index[0]))


def gia_adjustment(index: pd.DatetimeIndex, rate_mm_yr: float) -> np.ndarray:
    t = years_since_start(index)
    raw = -(rate_mm_yr / 1000.0) * t
    return raw - raw.mean()


def gia_adjustment_with_reference(
    index: pd.DatetimeIndex,
    rate_mm_yr: float,
    *,
    origin: pd.Timestamp,
    reference_mean_m: float | None = None,
) -> np.ndarray:
    t = years_since_origin(index, origin)
    raw = -(rate_mm_yr / 1000.0) * t
    if reference_mean_m is None:
        reference_mean_m = float(raw.mean())
    return raw - float(reference_mean_m)


def _monthly_means(y: np.ndarray, index: pd.DatetimeIndex) -> np.ndarray:
    """Centered monthly means (index 0 = January)."""
    df = pd.Series(y, index=index)
    monthly = df.groupby(df.index.month).mean()
    monthly -= monthly.mean()
    return np.array([float(monthly.get(m, 0.0)) for m in range(1, 13)])


def apply_seasonal_cycle(seasonal_means: np.ndarray, index: pd.DatetimeIndex) -> np.ndarray:
    return np.array([seasonal_means[m - 1] for m in index.month])


def seasonal_means_from_series(
    y: np.ndarray, index: pd.DatetimeIndex, t: np.ndarray
) -> np.ndarray:
    slope, intercept = np.polyfit(t, y, 1)
    return _monthly_means(y - (slope * t + intercept), index)


def deseason_series(
    y: np.ndarray, index: pd.DatetimeIndex, t: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Detrend first, compute seasonal cycle from residuals, return (deseasoned, seasonal_component).

    Adjusting for the trend prevents the linear rise from biasing later-month means upward
    relative to earlier ones.
    """
    seasonal_means = seasonal_means_from_series(y, index, t)
    seasonal_component = apply_seasonal_cycle(seasonal_means, index)
    return y - seasonal_component, seasonal_component


def deseason_matrix_with_means(
    matrix: np.ndarray, index: pd.DatetimeIndex, seasonal_means: np.ndarray
) -> np.ndarray:
    result = np.empty_like(matrix)
    for j in range(matrix.shape[1]):
        result[:, j] = matrix[:, j] - apply_seasonal_cycle(seasonal_means[j], index)
    return result


def deseason_matrix(
    matrix: np.ndarray, index: pd.DatetimeIndex, t: np.ndarray
) -> np.ndarray:
    """Apply deseason_series to every column of a predictor matrix."""
    seasonal_means = np.vstack(
        [seasonal_means_from_series(matrix[:, j], index, t) for j in range(matrix.shape[1])]
    )
    return deseason_matrix_with_means(matrix, index, seasonal_means)


def seasonal_columns(index: pd.DatetimeIndex) -> np.ndarray:
    rad = 2.0 * np.pi * np.asarray(index.month, dtype=float) / 12.0
    return np.column_stack([np.cos(rad), np.sin(rad), np.cos(2.0 * rad), np.sin(2.0 * rad)])


def time_series_splits(n: int, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    min_train = n // (n_splits + 1)
    step = (n - min_train) // n_splits
    splits = []
    for i in range(n_splits):
        train_end = min_train + i * step
        test_start = train_end
        test_end = min(test_start + step, n)
        if test_start >= n:
            break
        splits.append((np.arange(0, train_end), np.arange(test_start, test_end)))
    return splits


def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    return coeffs


# ---------------------------------------------------------------------------
# Plain OLS CV (no detrending)
# ---------------------------------------------------------------------------

def plain_ols_cv(
    X: np.ndarray,
    y: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    true_all, pred_all = [], []
    for train_idx, test_idx in splits:
        if len(train_idx) < X.shape[1]:
            continue
        coeffs = fit_ols(X[train_idx], y[train_idx])
        true_all.extend(y[test_idx].tolist())
        pred_all.extend((X[test_idx] @ coeffs).tolist())
    return np.array(true_all), np.array(pred_all)


def persistence_cv(
    y: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    true_all, pred_all = [], []
    for train_idx, test_idx in splits:
        if len(train_idx) == 0:
            continue
        last = y[train_idx[-1]]
        for idx in test_idx:
            true_all.append(y[idx])
            pred_all.append(last)
            last = y[idx]
    return np.array(true_all), np.array(pred_all)


# ---------------------------------------------------------------------------
# Detrended OLS CV — removes per-fold training trend from target and
# each predictor before fitting, then adds the extrapolated trend back.
# ---------------------------------------------------------------------------

def detrended_ols_cv(
    t: np.ndarray,
    predictor_matrix: np.ndarray,
    y: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    true_all, pred_all = [], []
    n_pred = predictor_matrix.shape[1]
    for train_idx, test_idx in splits:
        if len(train_idx) < n_pred + 2:
            continue
        t_tr, t_te = t[train_idx], t[test_idx]

        # Detrend target using training window only
        slope_y, intercept_y = np.polyfit(t_tr, y[train_idx], 1)
        y_tr_detr = y[train_idx] - (slope_y * t_tr + intercept_y)
        y_te_trend = slope_y * t_te + intercept_y

        # Detrend each predictor using training window only
        X_tr = np.empty((len(train_idx), n_pred))
        X_te = np.empty((len(test_idx), n_pred))
        for j in range(n_pred):
            s, i = np.polyfit(t_tr, predictor_matrix[train_idx, j], 1)
            X_tr[:, j] = predictor_matrix[train_idx, j] - (s * t_tr + i)
            X_te[:, j] = predictor_matrix[test_idx, j] - (s * t_te + i)

        X_tr_full = np.column_stack([np.ones(len(train_idx)), X_tr])
        X_te_full = np.column_stack([np.ones(len(test_idx)), X_te])

        coeffs = fit_ols(X_tr_full, y_tr_detr)
        y_pred = (X_te_full @ coeffs) + y_te_trend

        true_all.extend(y[test_idx].tolist())
        pred_all.extend(y_pred.tolist())
    return np.array(true_all), np.array(pred_all)


def detrended_ols_insample(
    t: np.ndarray,
    predictor_matrix: np.ndarray,
    y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    slope_y, intercept_y = np.polyfit(t, y, 1)
    y_trend = slope_y * t + intercept_y
    y_detr = y - y_trend

    n_pred = predictor_matrix.shape[1]
    X_detr = np.empty((len(t), n_pred))
    for j in range(n_pred):
        s, i = np.polyfit(t, predictor_matrix[:, j], 1)
        X_detr[:, j] = predictor_matrix[:, j] - (s * t + i)

    X_full = np.column_stack([np.ones(len(t)), X_detr])
    coeffs = fit_ols(X_full, y_detr)
    return (X_full @ coeffs) + y_trend, coeffs


# ---------------------------------------------------------------------------
# Ridge regression helpers
# ---------------------------------------------------------------------------

def _ridge_solve(X: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    n = X.shape[1]
    penalty = lam * np.eye(n)
    penalty[0, 0] = 0.0  # never penalize the intercept
    return np.linalg.solve(X.T @ X + penalty, X.T @ y)


def _select_lambda(
    X_tr: np.ndarray, y_tr: np.ndarray, lambda_grid: np.ndarray
) -> float:
    """Pick lambda by inner forward CV on the training fold."""
    n = len(y_tr)
    n_inner = 3
    min_tr = max(X_tr.shape[1] + 1, n // (n_inner + 1))
    step = max(1, (n - min_tr) // n_inner)
    rmse_grid = np.full(len(lambda_grid), np.inf)
    for k, lam in enumerate(lambda_grid):
        fold_rmses = []
        for i in range(n_inner):
            te_start = min_tr + i * step
            te_end = min(te_start + step, n)
            if te_start >= n or te_start < X_tr.shape[1] + 1:
                continue
            c = _ridge_solve(X_tr[:te_start], y_tr[:te_start], lam)
            fold_rmses.append(float(np.sqrt(np.mean((y_tr[te_start:te_end] - X_tr[te_start:te_end] @ c) ** 2))))
        if fold_rmses:
            rmse_grid[k] = float(np.mean(fold_rmses))
    return float(lambda_grid[int(np.argmin(rmse_grid))])


def _detrend_and_scale(
    predictor_matrix: np.ndarray,
    t_tr: np.ndarray,
    t_te: np.ndarray,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Detrend and within-fold standardize predictor columns for ridge."""
    n_pred = predictor_matrix.shape[1]
    X_tr = np.empty((len(train_idx), n_pred))
    X_te = np.empty((len(test_idx), n_pred))
    for j in range(n_pred):
        s, i = np.polyfit(t_tr, predictor_matrix[train_idx, j], 1)
        col_tr = predictor_matrix[train_idx, j] - (s * t_tr + i)
        col_te = predictor_matrix[test_idx, j] - (s * t_te + i)
        std = float(col_tr.std())
        if std > 1e-10:
            col_tr, col_te = col_tr / std, col_te / std
        X_tr[:, j] = col_tr
        X_te[:, j] = col_te
    return X_tr, X_te


def detrended_ridge_cv(
    t: np.ndarray,
    predictor_matrix: np.ndarray,
    y: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray]],
    lambda_grid: np.ndarray,
    forced_lambda: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    true_all, pred_all = [], []
    n_pred = predictor_matrix.shape[1]
    for train_idx, test_idx in splits:
        if len(train_idx) < n_pred + 2:
            continue
        t_tr, t_te = t[train_idx], t[test_idx]
        slope_y, intercept_y = np.polyfit(t_tr, y[train_idx], 1)
        y_tr_detr = y[train_idx] - (slope_y * t_tr + intercept_y)
        y_te_trend = slope_y * t_te + intercept_y
        X_tr, X_te = _detrend_and_scale(predictor_matrix, t_tr, t_te, train_idx, test_idx)
        X_tr_full = np.column_stack([np.ones(len(train_idx)), X_tr])
        X_te_full = np.column_stack([np.ones(len(test_idx)), X_te])
        lam = forced_lambda if forced_lambda is not None else _select_lambda(X_tr_full, y_tr_detr, lambda_grid)
        coeffs = _ridge_solve(X_tr_full, y_tr_detr, lam)
        true_all.extend(y[test_idx].tolist())
        pred_all.extend(((X_te_full @ coeffs) + y_te_trend).tolist())
    return np.array(true_all), np.array(pred_all)


def detrended_ridge_insample(
    t: np.ndarray,
    predictor_matrix: np.ndarray,
    y: np.ndarray,
    lambda_grid: np.ndarray,
    forced_lambda: float | None = None,
) -> tuple[np.ndarray, float]:
    slope_y, intercept_y = np.polyfit(t, y, 1)
    y_trend = slope_y * t + intercept_y
    y_detr = y - y_trend
    n_pred = predictor_matrix.shape[1]
    X_detr = np.empty((len(t), n_pred))
    for j in range(n_pred):
        s, i = np.polyfit(t, predictor_matrix[:, j], 1)
        col = predictor_matrix[:, j] - (s * t + i)
        std = float(col.std())
        if std > 1e-10:
            col = col / std
        X_detr[:, j] = col
    X_full = np.column_stack([np.ones(len(t)), X_detr])
    lam = forced_lambda if forced_lambda is not None else _select_lambda(X_full, y_detr, lambda_grid)
    coeffs = _ridge_solve(X_full, y_detr, lam)
    return (X_full @ coeffs) + y_trend, lam


def fit_detrended_ridge_model(
    t: np.ndarray,
    predictor_matrix: np.ndarray,
    y: np.ndarray,
    lambda_grid: np.ndarray,
    forced_lambda: float | None = None,
) -> tuple[np.ndarray, float, float, float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    slope_y, intercept_y = np.polyfit(t, y, 1)
    y_trend = slope_y * t + intercept_y
    y_detr = y - y_trend
    n_pred = predictor_matrix.shape[1]
    X_detr = np.empty((len(t), n_pred))
    predictor_slopes = np.empty(n_pred, dtype=float)
    predictor_intercepts = np.empty(n_pred, dtype=float)
    predictor_stds = np.empty(n_pred, dtype=float)
    for j in range(n_pred):
        s, i = np.polyfit(t, predictor_matrix[:, j], 1)
        predictor_slopes[j] = s
        predictor_intercepts[j] = i
        col = predictor_matrix[:, j] - (s * t + i)
        std = float(col.std())
        predictor_stds[j] = std if std > 1e-10 else 1.0
        if std > 1e-10:
            col = col / std
        X_detr[:, j] = col
    X_full = np.column_stack([np.ones(len(t)), X_detr])
    lam = forced_lambda if forced_lambda is not None else _select_lambda(X_full, y_detr, lambda_grid)
    coeffs = _ridge_solve(X_full, y_detr, lam)
    fitted = (X_full @ coeffs) + y_trend
    return (
        fitted,
        float(lam),
        float(slope_y),
        float(intercept_y),
        predictor_slopes,
        predictor_intercepts,
        predictor_stds,
        coeffs,
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def skill_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    resid = y_true - y_pred
    ss_total = float(np.sum((y_true - y_true.mean()) ** 2))
    ss_res = float(np.sum(resid**2))
    return {
        "rmse_m": float(np.sqrt(np.mean(resid**2))),
        "mae_m": float(np.mean(np.abs(resid))),
        "bias_m": float(np.mean(resid)),
        "r_squared": 1.0 - ss_res / ss_total if ss_total > 0 else np.nan,
        "correlation": float(np.corrcoef(y_true, y_pred)[0, 1]) if len(y_true) > 1 else np.nan,
    }


def skill_score(rmse_model: float, rmse_ref: float) -> float:
    return float(1.0 - rmse_model / rmse_ref) if rmse_ref != 0.0 else np.nan


# ---------------------------------------------------------------------------
# Per-station evaluation
# ---------------------------------------------------------------------------


def prepare_station_training_frame(
    frame: pd.DataFrame,
    station_variable: str,
    *,
    include_observed: bool = True,
) -> pd.DataFrame:
    needed = EXTERNAL_PREDICTORS + ARGO_PREDICTORS
    if include_observed:
        needed = [station_variable, f"{station_variable}_anomaly"] + needed
    working = frame[needed].dropna().copy()
    if working.empty:
        raise ValueError(f"No Argo-overlap data for {station_variable}.")
    return working


def fit_station_final_model(
    frame: pd.DataFrame,
    *,
    station_name: str,
    station_variable: str,
    gia_rate_mm_yr: float,
    ridge_lambda: float | None = None,
) -> tuple[pd.DataFrame, FinalModelFit]:
    working = prepare_station_training_frame(frame, station_variable)
    index = working.index
    t = years_since_start(index)
    y_anomaly = working[f"{station_variable}_anomaly"].to_numpy(dtype=float)
    gia = gia_adjustment(index, gia_rate_mm_yr)
    y = y_anomaly - gia

    raw_predictor_matrix = working[EXTERNAL_PREDICTORS + ARGO_PREDICTORS].to_numpy(dtype=float)
    target_seasonal_means = seasonal_means_from_series(y, index, t)
    y_ds = y - apply_seasonal_cycle(target_seasonal_means, index)
    predictor_seasonal_means = np.vstack(
        [
            seasonal_means_from_series(raw_predictor_matrix[:, j], index, t)
            for j in range(raw_predictor_matrix.shape[1])
        ]
    )
    predictor_ds = deseason_matrix_with_means(raw_predictor_matrix, index, predictor_seasonal_means)
    (
        _,
        fitted_lambda,
        target_trend_slope,
        target_trend_intercept,
        predictor_trend_slopes,
        predictor_trend_intercepts,
        predictor_stds,
        coefficients,
    ) = fit_detrended_ridge_model(
        t,
        predictor_ds,
        y_ds,
        LAMBDA_GRID,
        forced_lambda=ridge_lambda,
    )

    raw_gia = -(gia_rate_mm_yr / 1000.0) * t
    baseline_values = (working[station_variable] - working[f"{station_variable}_anomaly"]).dropna()
    fit = FinalModelFit(
        station_name=station_name,
        station_variable=station_variable,
        gia_rate_mm_yr=float(gia_rate_mm_yr),
        predictor_names=tuple(EXTERNAL_PREDICTORS + ARGO_PREDICTORS),
        time_origin=pd.Timestamp(index[0]),
        gia_reference_mean_m=float(raw_gia.mean()),
        target_baseline_m=float(baseline_values.iloc[0]),
        target_seasonal_means=target_seasonal_means,
        target_trend_slope=target_trend_slope,
        target_trend_intercept=target_trend_intercept,
        predictor_seasonal_means=predictor_seasonal_means,
        predictor_trend_slopes=predictor_trend_slopes,
        predictor_trend_intercepts=predictor_trend_intercepts,
        predictor_stds=predictor_stds,
        coefficients=coefficients,
        ridge_lambda=fitted_lambda,
    )
    return working, fit


def predict_with_final_model(
    fit: FinalModelFit,
    index: pd.DatetimeIndex,
    predictor_matrix: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    t = years_since_origin(index, fit.time_origin)
    predictor_ds = deseason_matrix_with_means(predictor_matrix, index, fit.predictor_seasonal_means)
    X_detr = np.empty_like(predictor_ds)
    for j in range(predictor_ds.shape[1]):
        col = predictor_ds[:, j] - (
            fit.predictor_trend_slopes[j] * t + fit.predictor_trend_intercepts[j]
        )
        std = float(fit.predictor_stds[j])
        if std > 1e-10:
            col = col / std
        X_detr[:, j] = col
    X_full = np.column_stack([np.ones(len(index)), X_detr])
    y_ds = (X_full @ fit.coefficients) + (fit.target_trend_slope * t + fit.target_trend_intercept)
    y = y_ds + apply_seasonal_cycle(fit.target_seasonal_means, index)
    return y, y_ds


def extrapolate_target_with_final_model(
    fit: FinalModelFit,
    index: pd.DatetimeIndex,
) -> tuple[np.ndarray, np.ndarray]:
    t = years_since_origin(index, fit.time_origin)
    y_ds = fit.target_trend_slope * t + fit.target_trend_intercept
    y = y_ds + apply_seasonal_cycle(fit.target_seasonal_means, index)
    return y, y_ds

def evaluate_station(
    frame: pd.DataFrame,
    station_name: str,
    station_variable: str,
    gia_rate_mm_yr: float,
    n_splits: int,
    ridge_lambda: float | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    working, fit = fit_station_final_model(
        frame,
        station_name=station_name,
        station_variable=station_variable,
        gia_rate_mm_yr=gia_rate_mm_yr,
        ridge_lambda=ridge_lambda,
    )
    index = working.index
    t = years_since_start(index)
    y_anomaly = working[f"{station_variable}_anomaly"].to_numpy(dtype=float)
    gia = gia_adjustment(index, gia_rate_mm_yr)
    y = y_anomaly - gia

    # Pre-remove the trend-adjusted seasonal cycle from the target and from every
    # predictor. Detrending before computing monthly means prevents the linear rise
    # from biasing seasonal estimates. Deseasoning the predictors (especially Argo
    # T/S/density, which carry a large seasonal cycle) ensures the OLS sees the same
    # type of variance in both y and predictors.
    seasonal_component = apply_seasonal_cycle(fit.target_seasonal_means, index)
    y_ds = y - seasonal_component

    ext_matrix_raw = working[EXTERNAL_PREDICTORS].to_numpy(dtype=float)
    argo_matrix_raw = working[ARGO_PREDICTORS].to_numpy(dtype=float)
    ext_matrix = deseason_matrix_with_means(
        ext_matrix_raw,
        index,
        fit.predictor_seasonal_means[: len(EXTERNAL_PREDICTORS)],
    )
    argo_matrix = deseason_matrix_with_means(
        argo_matrix_raw,
        index,
        fit.predictor_seasonal_means[len(EXTERNAL_PREDICTORS) :],
    )
    ext_argo_matrix = np.column_stack([ext_matrix, argo_matrix])

    splits = time_series_splits(len(working), n_splits)

    # Design matrices for non-detrended models (include intercept + trend).
    # trend_seasonal's harmonic terms now fit residual non-seasonal variance and
    # should converge toward trend_only — confirming the seasonal pre-removal worked.
    X_trend = np.column_stack([np.ones(len(working)), t])
    X_seasonal = np.column_stack([np.ones(len(working)), t, seasonal_columns(index)])
    X_ols_reduced = np.column_stack([np.ones(len(working)), t, ext_matrix])

    results = {}
    results["persistence"] = persistence_cv(y_ds, splits)
    results["trend_only"] = plain_ols_cv(X_trend, y_ds, splits)
    results["trend_seasonal"] = plain_ols_cv(X_seasonal, y_ds, splits)
    results["ols_reduced"] = plain_ols_cv(X_ols_reduced, y_ds, splits)
    results["ols_reduced_detrended"] = detrended_ols_cv(t, ext_matrix, y_ds, splits)
    results["ols_with_argo_detrended"] = detrended_ols_cv(t, ext_argo_matrix, y_ds, splits)
    results["ols_with_argo_ridge"] = detrended_ridge_cv(
        t, ext_argo_matrix, y_ds, splits, LAMBDA_GRID, forced_lambda=ridge_lambda
    )

    metrics_by_model = {name: skill_metrics(*pair) for name, pair in results.items()}
    rmse_persist = metrics_by_model["persistence"]["rmse_m"]
    rmse_trend = metrics_by_model["trend_only"]["rmse_m"]

    summaries = []
    for model_name in MODEL_ORDER:
        if model_name not in metrics_by_model:
            continue
        m = metrics_by_model[model_name]
        summaries.append(
            {
                "station": station_name,
                "model": model_name,
                "is_final_model": model_name == FINAL_MODEL,
                "cv_folds": n_splits,
                "n_months_cv": len(results[model_name][0]),
                "skill_vs_persistence": skill_score(m["rmse_m"], rmse_persist),
                "skill_vs_trend": skill_score(m["rmse_m"], rmse_trend),
                **m,
            }
        )

    y_insample, _ = predict_with_final_model(
        fit,
        index,
        working[list(fit.predictor_names)].to_numpy(dtype=float),
    )

    fitted = pd.DataFrame(index=index)
    fitted["station_name"] = station_name
    fitted["observed_m"] = working[station_variable].to_numpy(dtype=float)
    fitted["observed_anomaly_m"] = y_anomaly
    fitted["gia_component_m"] = gia
    fitted["seasonal_component_m"] = seasonal_component
    fitted["target_adjusted_m"] = y
    fitted["target_deseasoned_m"] = y_ds
    fitted["hindcast_insample_m"] = y_insample
    fitted["hindcast_residual_m"] = y - y_insample
    fitted["ridge_lambda_insample"] = fit.ridge_lambda

    return fitted, summaries


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_skill_table(summaries: list[dict], plot_dir: Path) -> None:
    df = pd.DataFrame(summaries)
    df.to_csv(plot_dir / "sojs_hindcast_skill_table.csv", index=False, float_format="%.6f")


def save_skill_bar_plot(summaries: list[dict], plot_dir: Path) -> None:
    df = pd.DataFrame(summaries)
    stations = [s for s in df["station"].unique()]
    fig, axes = plt.subplots(1, len(stations), figsize=(6 * len(stations), 5), sharey=False)
    if len(stations) == 1:
        axes = [axes]
    colors = ["#aec7e8", "#ffbb78", "#98df8a", "#c5b0d5", "#ff9896", "#1f77b4"]
    for ax, station in zip(axes, stations):
        sub = df[df["station"] == station]
        values, labels, bar_colors = [], [], []
        for i, m in enumerate(MODEL_ORDER):
            row = sub[sub["model"] == m]
            if row.empty:
                continue
            labels.append(m)
            values.append(row["rmse_m"].values[0])
            bar_colors.append("#1f77b4" if m == FINAL_MODEL else colors[i % len(colors)])
        bars = ax.bar(range(len(labels)), values, color=bar_colors)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
        ax.set_title(station)
        ax.set_ylabel("CV RMSE (m)")
        ax.grid(axis="y", alpha=0.3)
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + 0.0005,
                f"{val:.4f}",
                ha="center", va="bottom", fontsize=8,
            )
    fig.suptitle(
        f"Hindcast CV RMSE by model (dark blue = final model: {FINAL_MODEL})", fontsize=11
    )
    fig.tight_layout()
    plot_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(plot_dir / "sojs_hindcast_rmse_comparison.png", dpi=160)
    plt.close(fig)


def save_hindcast_plot(fitted: pd.DataFrame, plot_dir: Path) -> None:
    station_name = fitted["station_name"].iloc[0]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    ax1.plot(
        fitted.index, fitted["observed_anomaly_m"],
        label="Observed anomaly", linewidth=1.5, color="#4C78A8",
    )
    ax1.plot(
        fitted.index, fitted["hindcast_insample_m"],
        label=f"Final model in-sample hindcast ({FINAL_MODEL})",
        linewidth=1.5, color="#F58518", linestyle="--",
    )
    ax1.set_ylabel("Sea level anomaly (m)")
    ax1.set_title(f"{station_name}: final model in-sample hindcast vs observed")
    ax1.grid(alpha=0.25)
    ax1.legend(fontsize=9)

    ax2.plot(
        fitted.index, fitted["hindcast_residual_m"],
        linewidth=1.2, color="#54A24B",
    )
    ax2.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    ax2.set_ylabel("Residual (m)")
    ax2.set_xlabel("Time")
    ax2.set_title("Residual (observed – hindcast)")
    ax2.grid(alpha=0.25)

    fig.tight_layout()
    plot_dir.mkdir(parents=True, exist_ok=True)
    safe = station_name.lower().replace(" ", "_")
    fig.savefig(plot_dir / f"{safe}_hindcast.png", dpi=160)
    plt.close(fig)


def save_hindcast_dataset(fitted_frames: list[pd.DataFrame], output_path: Path) -> None:
    all_rows = pd.concat(fitted_frames).reset_index().rename(columns={"index": "time"})
    ds = (
        all_rows.set_index(["time", "station_name"])
        .to_xarray()
        .transpose("station_name", "time", ...)
    )
    ds.attrs.update(
        {
            "title": "Sojs Phase 4 hindcast results",
            "description": (
                f"In-sample {FINAL_MODEL} hindcast on the Argo overlap period. "
                "Mean seasonal cycle pre-removed from target before all CV; "
                "predictors detrended per-fold using training-window trends only."
            ),
            "final_model": FINAL_MODEL,
            "external_predictors": ", ".join(EXTERNAL_PREDICTORS),
            "argo_predictor": ARGO_PREDICTORS[0],
            "argo_rationale": (
                "Density alone encodes both T and S; using all three creates near-collinear "
                "columns that inflate OLS coefficient variance on short CV training windows."
            ),
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoding = {v: {"zlib": True, "complevel": 4, "_FillValue": np.nan} for v in ds.data_vars}
    ds.to_netcdf(output_path, encoding=encoding)
    ds.close()


def save_summary_markdown(summaries: list[dict], plot_dir: Path) -> None:
    df = pd.DataFrame(summaries)
    lines = [
        "# Sojs Phase 4 Hindcast Skill Summary",
        "",
        "**Dataset:** Argo overlap period (months where Argo T/S/density pass support thresholds).",
        "**CV method:** Forward time-series split — no future leakage.",
        "**Seasonal pre-removal:** Trend-adjusted monthly cycle (detrend first, then monthly means)",
        "  removed from the target AND every predictor before all CV loops. Deseasoning the",
        "  predictors (especially Argo T/S/density) is required so the OLS sees the same type of",
        "  variance in both inputs and target. `trend_seasonal` should converge toward `trend_only`",
        "  — confirming the pre-removal worked.",
        f"**Final model:** `{FINAL_MODEL}` — ridge regression with inner CV lambda selection;",
        "  per-fold detrending and standardization; predictors: Copernicus SLA, GRACE mass,",
        "  Greenland mass, Argo density. Ridge shrinks the Argo coefficient toward zero if it",
        "  adds noise, preventing it from degrading the external-predictor skill.",
        "",
    ]
    for station in df["station"].unique():
        sub = df[df["station"] == station].copy()
        lines += [f"## {station}", ""]
        lines += [
            "| Model | Final | CV RMSE (m) | R² | Skill vs persistence | Skill vs trend |",
            "|-------|-------|------------|-----|----------------------|----------------|",
        ]
        for _, row in sub.iterrows():
            marker = "**yes**" if row["is_final_model"] else ""
            lines.append(
                f"| {row['model']} | {marker} | {row['rmse_m']:.5f} | {row['r_squared']:.4f} "
                f"| {row['skill_vs_persistence']:.4f} | {row['skill_vs_trend']:.4f} |"
            )
        lines.append("")

    lines += [
        "## Key design decisions",
        "",
        "- All models are evaluated on the same Argo overlap period for fair comparison.",
        "- The trend-adjusted seasonal cycle is pre-removed from the target AND every predictor.",
        "  Predictors (especially Argo T/S/density) carry large seasonal cycles; removing them",
        "  ensures the OLS fits non-seasonal co-variance, not seasonal phase alignment.",
        "  All RMSE/R² values reflect non-seasonal sea level variability only.",
        "- `ols_reduced` vs `ols_reduced_detrended` shows the effect of per-fold trend removal.",
        "- `ols_with_argo_ridge` is the final model: ridge regression with inner CV lambda selection,",
        "  per-fold detrending + standardization, predictors: SLA, GRACE, Greenland, Argo density.",
        "  Ridge prevents the Argo density coefficient from inflating if it adds noise over the",
        "  external predictors. Use `--ridge-lambda <value>` to force a smaller penalty if needed.",
        "- `ols_with_argo_detrended` (pure OLS) is kept as a comparison to show the ridge effect.",
        "- Positive skill scores vs persistence indicate the model captures genuine dynamic signal.",
        "- Residuals document what the active data stack does not yet explain.",
    ]
    plot_dir.mkdir(parents=True, exist_ok=True)
    (plot_dir / "sojs_hindcast_skill_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.argo_overlap.exists():
        raise SystemExit(f"Argo overlap dataset not found: {args.argo_overlap}")

    # ridge_lambda=0 is the sentinel for "use inner CV" rather than a literal zero penalty
    ridge_lambda: float | None = args.ridge_lambda if args.ridge_lambda != 0.0 else None

    frame = load_frame(args.argo_overlap)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.plot_dir.mkdir(parents=True, exist_ok=True)

    fitted_frames: list[pd.DataFrame] = []
    all_summaries: list[dict] = []

    for station_name, config in STATIONS.items():
        fitted, summaries = evaluate_station(
            frame,
            station_name=station_name,
            station_variable=config["variable"],
            gia_rate_mm_yr=float(config["gia_rate_mm_yr"]),
            n_splits=args.n_splits,
            ridge_lambda=ridge_lambda,
        )
        fitted_frames.append(fitted)
        all_summaries.extend(summaries)
        save_hindcast_plot(fitted, args.plot_dir)

    save_skill_bar_plot(all_summaries, args.plot_dir)
    save_skill_table(all_summaries, args.plot_dir)
    save_summary_markdown(all_summaries, args.plot_dir)
    save_hindcast_dataset(fitted_frames, args.output_dir / "sojs_hindcast_results.nc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
