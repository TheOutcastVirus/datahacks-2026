from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "matplotlib is not installed. Run `pip install -r requirements.txt` first."
    ) from exc


DEFAULT_TRAINING_PATH = Path("data/annual/sojs_portland_annual_training.csv")
DEFAULT_OUTPUT_DIR = Path("data/annual")
DEFAULT_PLOT_DIR = Path("plots/annual")
DEFAULT_BOOTSTRAPS = 200
DEFAULT_MIN_TRAIN_YEARS = 12
DEFAULT_INTERVAL_Z = 1.2815515655446004
DEFAULT_RIDGE_LAMBDA = 1.0
MODEL_JSON_NAME = "sojs_portland_annual_model.json"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    predictors: tuple[str, ...]
    use_ridge: bool = False
    ridge_lambda: float = DEFAULT_RIDGE_LAMBDA


MODEL_SPECS = [
    ModelSpec("baseline_trend", ()),
    ModelSpec(
        "trend_plus_nao",
        (
            "nao_annual_mean",
            "nao_winter_djf",
            "nao_annual_mean_prev_year",
            "nao_winter_djf_prev_year",
        ),
    ),
    ModelSpec(
        "trend_plus_nao_plus_sla",
        (
            "nao_annual_mean",
            "nao_winter_djf",
            "nao_annual_mean_prev_year",
            "nao_winter_djf_prev_year",
            "copernicus_sla_gom_m",
            "copernicus_sla_gom_m_lag1",
        ),
    ),
    ModelSpec(
        "trend_plus_nao_plus_sla_plus_greenland",
        (
            "nao_annual_mean",
            "nao_winter_djf",
            "nao_annual_mean_prev_year",
            "nao_winter_djf_prev_year",
            "copernicus_sla_gom_m",
            "copernicus_sla_gom_m_lag1",
            "greenland_mass_gt",
        ),
    ),
    ModelSpec(
        "trend_plus_nao_plus_sla_plus_greenland_ridge",
        (
            "nao_annual_mean",
            "nao_winter_djf",
            "nao_annual_mean_prev_year",
            "nao_winter_djf_prev_year",
            "copernicus_sla_gom_m",
            "copernicus_sla_gom_m_lag1",
            "greenland_mass_gt",
        ),
        use_ridge=True,
        ridge_lambda=DEFAULT_RIDGE_LAMBDA,
    ),
]
SCENARIO_CAPABLE_MODELS = {
    "trend_plus_nao",
    "trend_plus_nao_plus_sla",
    "trend_plus_nao_plus_sla_plus_greenland",
    "trend_plus_nao_plus_sla_plus_greenland_ridge",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit the Sojs annual Portland model ladder, run annual rolling-origin "
            "backtests, and save the selected annual model."
        )
    )
    parser.add_argument("--training-path", type=Path, default=DEFAULT_TRAINING_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--bootstraps", type=int, default=DEFAULT_BOOTSTRAPS)
    parser.add_argument("--min-train-years", type=int, default=DEFAULT_MIN_TRAIN_YEARS)
    parser.add_argument("--ridge-lambda", type=float, default=DEFAULT_RIDGE_LAMBDA)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if not args.training_path.exists():
        raise SystemExit(f"Annual training table not found: {args.training_path}")
    if args.bootstraps < 10:
        raise SystemExit("--bootstraps must be at least 10.")
    if args.min_train_years < 5:
        raise SystemExit("--min-train-years must be at least 5.")
    if args.ridge_lambda < 0.0:
        raise SystemExit("--ridge-lambda must be zero or greater.")


def load_training_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["year"] = frame["year"].astype(int)
    frame["copernicus_sla_gom_m_lag1"] = frame["copernicus_sla_gom_m"].shift(1)
    frame["target_baseline_m"] = frame["portland_msl_m"] - frame["portland_msl_m_anomaly"]
    return frame.sort_values("year", kind="stable").reset_index(drop=True)


def years_since_origin(years: np.ndarray, origin: int) -> np.ndarray:
    return years.astype(float) - float(origin)


def prepare_model_frame(frame: pd.DataFrame, spec: ModelSpec) -> pd.DataFrame:
    needed = [
        "year",
        "portland_target_adjusted_m",
        "portland_msl_m",
        "portland_msl_m_anomaly",
        "target_baseline_m",
        "relative_land_motion_mm_yr",
        "relative_land_motion_sigma_mm_yr",
        "land_motion_adjustment_m",
        "land_motion_kind",
        "land_motion_source",
    ]
    needed.extend(spec.predictors)
    working = frame[needed].dropna().copy()
    return working.reset_index(drop=True)


def fit_linear_model(
    train: pd.DataFrame,
    spec: ModelSpec,
) -> dict[str, object]:
    years = train["year"].to_numpy(dtype=int)
    origin = int(years[0])
    trend = years_since_origin(years, origin)
    X_parts = [np.ones(len(train), dtype=float), trend]
    predictor_means: dict[str, float] = {}
    predictor_stds: dict[str, float] = {}
    standardized_columns: list[np.ndarray] = []

    for predictor in spec.predictors:
        column = train[predictor].to_numpy(dtype=float)
        mean = float(column.mean())
        std = float(column.std(ddof=0))
        if std <= 1e-12:
            std = 1.0
        predictor_means[predictor] = mean
        predictor_stds[predictor] = std
        standardized_columns.append((column - mean) / std)

    if standardized_columns:
        X_parts.append(np.column_stack(standardized_columns))
    X = np.column_stack(X_parts)
    y = train["portland_target_adjusted_m"].to_numpy(dtype=float)

    if spec.use_ridge and X.shape[1] > 1:
        penalty = spec.ridge_lambda * np.eye(X.shape[1])
        penalty[0, 0] = 0.0
        coefficients = np.linalg.solve(X.T @ X + penalty, X.T @ y)
    else:
        coefficients, _, _, _ = np.linalg.lstsq(X, y, rcond=None)

    fitted = X @ coefficients
    residuals = y - fitted
    residual_sigma = float(residuals.std(ddof=1)) if len(residuals) > 1 else 0.0
    relative_land_motion_mm_yr = float(train["relative_land_motion_mm_yr"].iloc[0])
    raw_land_motion = -(
        relative_land_motion_mm_yr / 1000.0
    ) * years_since_origin(years, origin)
    return {
        "spec": spec,
        "origin_year": origin,
        "coefficients": coefficients,
        "predictor_means": predictor_means,
        "predictor_stds": predictor_stds,
        "residual_sigma_m": residual_sigma,
        "train_years": years.tolist(),
        "target_baseline_m": float(train["target_baseline_m"].dropna().iloc[0]),
        "relative_land_motion_mm_yr": relative_land_motion_mm_yr,
        "relative_land_motion_sigma_mm_yr": float(train["relative_land_motion_sigma_mm_yr"].iloc[0]),
        "land_motion_reference_year": int(origin),
        "land_motion_reference_mean_m": float(raw_land_motion.mean()),
        "land_motion_kind": str(train["land_motion_kind"].iloc[0]),
        "land_motion_source": str(train["land_motion_source"].iloc[0]),
    }


def predict_linear_model(fit: dict[str, object], frame: pd.DataFrame) -> np.ndarray:
    spec: ModelSpec = fit["spec"]
    years = frame["year"].to_numpy(dtype=int)
    trend = years_since_origin(years, int(fit["origin_year"]))
    X_parts = [np.ones(len(frame), dtype=float), trend]
    if spec.predictors:
        standardized = []
        for predictor in spec.predictors:
            mean = float(fit["predictor_means"][predictor])
            std = float(fit["predictor_stds"][predictor])
            standardized.append((frame[predictor].to_numpy(dtype=float) - mean) / std)
        X_parts.append(np.column_stack(standardized))
    X = np.column_stack(X_parts)
    return X @ np.asarray(fit["coefficients"], dtype=float)


def land_motion_adjustment_for_years(
    years: np.ndarray,
    *,
    rate_mm_yr: float,
    origin_year: int,
    reference_mean_m: float,
) -> np.ndarray:
    raw = -(rate_mm_yr / 1000.0) * (years.astype(float) - float(origin_year))
    return raw - float(reference_mean_m)


def absolute_prediction(frame: pd.DataFrame, fit: dict[str, object], adjusted_prediction: np.ndarray) -> np.ndarray:
    years = frame["year"].to_numpy(dtype=int)
    land_motion = land_motion_adjustment_for_years(
        years,
        rate_mm_yr=float(fit["relative_land_motion_mm_yr"]),
        origin_year=int(fit["land_motion_reference_year"]),
        reference_mean_m=float(fit["land_motion_reference_mean_m"]),
    )
    anomaly = adjusted_prediction + land_motion
    return anomaly + float(fit["target_baseline_m"])


def compute_metrics(
    observed: np.ndarray,
    predicted: np.ndarray,
    *,
    interval_sigma_m: float,
) -> dict[str, float]:
    residuals = observed - predicted
    rmse = float(np.sqrt(np.mean(residuals**2)))
    mae = float(np.mean(np.abs(residuals)))
    bias = float(np.mean(residuals))
    lower = predicted - DEFAULT_INTERVAL_Z * interval_sigma_m
    upper = predicted + DEFAULT_INTERVAL_Z * interval_sigma_m
    coverage = float(np.mean((observed >= lower) & (observed <= upper)))
    if len(observed) > 1:
        obs_slope = float(np.polyfit(np.arange(len(observed)), observed, 1)[0])
        pred_slope = float(np.polyfit(np.arange(len(predicted)), predicted, 1)[0])
        trend_error = pred_slope - obs_slope
    else:
        trend_error = np.nan
    return {
        "rmse_m": rmse,
        "mae_m": mae,
        "bias_m": bias,
        "trend_error_m_per_year": trend_error,
        "interval_coverage_80": coverage,
    }


def rolling_splits(
    years: np.ndarray,
    *,
    horizon: int,
    min_train_years: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    n = len(years)
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for train_end in range(min_train_years, n - horizon + 1):
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(train_end, train_end + horizon)
        splits.append((train_idx, test_idx))
    return splits


def evaluate_spec(
    frame: pd.DataFrame,
    spec: ModelSpec,
    *,
    min_train_years: int,
) -> tuple[pd.DataFrame, dict[str, float]]:
    working = prepare_model_frame(frame, spec)
    rows: list[dict[str, object]] = []
    if working.empty:
        return pd.DataFrame(rows), {}

    for horizon in (5, 10):
        for split_index, (train_idx, test_idx) in enumerate(
            rolling_splits(
                working["year"].to_numpy(dtype=int),
                horizon=horizon,
                min_train_years=min_train_years,
            ),
            start=1,
        ):
            train = working.iloc[train_idx].copy()
            test = working.iloc[test_idx].copy()
            if len(train) < max(3, len(spec.predictors) + 3):
                continue
            fit = fit_linear_model(train, spec)
            predicted_adjusted = predict_linear_model(fit, test)
            predicted = absolute_prediction(test, fit, predicted_adjusted)
            observed = test["portland_msl_m"].to_numpy(dtype=float)
            metrics = compute_metrics(
                observed,
                predicted,
                interval_sigma_m=float(fit["residual_sigma_m"]),
            )
            rows.append(
                {
                    "model": spec.name,
                    "evaluation": f"rolling_origin_{horizon}y",
                    "horizon_years": horizon,
                    "split_index": split_index,
                    "train_start_year": int(train["year"].iloc[0]),
                    "train_end_year": int(train["year"].iloc[-1]),
                    "test_start_year": int(test["year"].iloc[0]),
                    "test_end_year": int(test["year"].iloc[-1]),
                    "train_years": int(len(train)),
                    "test_years": int(len(test)),
                    "ridge_lambda": float(spec.ridge_lambda if spec.use_ridge else 0.0),
                    **metrics,
                }
            )

    tail_horizon = 10
    if len(working) >= min_train_years + tail_horizon:
        train = working.iloc[:-tail_horizon].copy()
        test = working.iloc[-tail_horizon:].copy()
        fit = fit_linear_model(train, spec)
        predicted = absolute_prediction(test, fit, predict_linear_model(fit, test))
        observed = test["portland_msl_m"].to_numpy(dtype=float)
        metrics = compute_metrics(
            observed,
            predicted,
            interval_sigma_m=float(fit["residual_sigma_m"]),
        )
        rows.append(
            {
                "model": spec.name,
                "evaluation": "tail_holdout_10y",
                "horizon_years": tail_horizon,
                "split_index": 1,
                "train_start_year": int(train["year"].iloc[0]),
                "train_end_year": int(train["year"].iloc[-1]),
                "test_start_year": int(test["year"].iloc[0]),
                "test_end_year": int(test["year"].iloc[-1]),
                "train_years": int(len(train)),
                "test_years": int(len(test)),
                "ridge_lambda": float(spec.ridge_lambda if spec.use_ridge else 0.0),
                **metrics,
            }
        )

    results = pd.DataFrame(rows)
    if results.empty:
        return results, {}

    horizon_mask = results["evaluation"] == "rolling_origin_5y"
    summary = {
        "model": spec.name,
        "n_years": int(len(working)),
        "time_start_year": int(working["year"].iloc[0]),
        "time_end_year": int(working["year"].iloc[-1]),
        "mean_rmse_5y": float(results.loc[horizon_mask, "rmse_m"].mean()) if horizon_mask.any() else np.nan,
        "mean_rmse_10y": float(
            results.loc[results["evaluation"] == "rolling_origin_10y", "rmse_m"].mean()
        )
        if (results["evaluation"] == "rolling_origin_10y").any()
        else np.nan,
        "tail_rmse_10y": float(results.loc[results["evaluation"] == "tail_holdout_10y", "rmse_m"].mean())
        if (results["evaluation"] == "tail_holdout_10y").any()
        else np.nan,
        "mean_interval_coverage_80": float(results["interval_coverage_80"].mean()),
    }
    return results, summary


def select_final_model(summaries: pd.DataFrame) -> str:
    eligible = summaries[summaries["model"].isin(SCENARIO_CAPABLE_MODELS)].copy()
    eligible = eligible.sort_values(
        ["mean_rmse_5y", "mean_rmse_10y", "tail_rmse_10y"],
        kind="stable",
        na_position="last",
    )
    if eligible.empty:
        return "baseline_trend"
    return str(eligible.iloc[0]["model"])


def fit_bootstrap_coefficients(
    working: pd.DataFrame,
    spec: ModelSpec,
    *,
    n_bootstraps: int,
) -> tuple[np.ndarray, list[int]]:
    fit = fit_linear_model(working, spec)
    fitted = predict_linear_model(fit, working)
    observed = working["portland_target_adjusted_m"].to_numpy(dtype=float)
    residuals = observed - fitted
    rng = np.random.default_rng(20260419)
    bootstrap_coeffs = []
    for _ in range(n_bootstraps):
        sampled = rng.choice(residuals, size=len(residuals), replace=True)
        boot = working.copy()
        boot["portland_target_adjusted_m"] = fitted + sampled
        boot_fit = fit_linear_model(boot, spec)
        bootstrap_coeffs.append(np.asarray(boot_fit["coefficients"], dtype=float))
    return np.vstack(bootstrap_coeffs), fit["train_years"]


def save_backtest_plot(
    frame: pd.DataFrame,
    summaries: pd.DataFrame,
    selected_fit: dict[str, object],
    selected_spec: ModelSpec,
    path: Path,
) -> None:
    working = prepare_model_frame(frame, selected_spec)
    years = working["year"].to_numpy(dtype=int)
    observed = working["portland_msl_m"].to_numpy(dtype=float)
    fitted_adjusted = predict_linear_model(selected_fit, working)
    fitted = absolute_prediction(working, selected_fit, fitted_adjusted)

    tail_horizon = 10
    tail = working.iloc[-tail_horizon:].copy() if len(working) >= tail_horizon else working.copy()
    tail_fit = fit_linear_model(working.iloc[:-tail_horizon], selected_spec) if len(working) > tail_horizon else selected_fit
    tail_pred = absolute_prediction(tail, tail_fit, predict_linear_model(tail_fit, tail))
    tail_sigma = float(tail_fit["residual_sigma_m"])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), height_ratios=[2.2, 1.4])
    ax1.plot(years, observed, color="#2f4b7c", linewidth=1.6, label="Observed Portland annual mean")
    ax1.plot(years, fitted, color="#f58518", linewidth=1.5, linestyle="--", label=f"Fitted {selected_spec.name}")
    ax1.fill_between(
        tail["year"].to_numpy(dtype=int),
        tail_pred - DEFAULT_INTERVAL_Z * tail_sigma,
        tail_pred + DEFAULT_INTERVAL_Z * tail_sigma,
        color="#f58518",
        alpha=0.2,
        label="Tail holdout 80% band",
    )
    ax1.plot(
        tail["year"].to_numpy(dtype=int),
        tail_pred,
        color="#f58518",
        linewidth=2.0,
    )
    ax1.set_title("Sojs annual backtest: observed Portland annual mean vs fitted/tail-holdout prediction")
    ax1.set_ylabel("Sea level (m)")
    ax1.grid(alpha=0.25)
    ax1.legend(fontsize=9)

    metric_table = summaries.set_index("model")[["mean_rmse_5y", "mean_rmse_10y"]].dropna(how="all")
    positions = np.arange(len(metric_table.index))
    width = 0.35
    ax2.bar(positions - width / 2, metric_table["mean_rmse_5y"], width=width, color="#4c78a8", label="Rolling 5y mean RMSE")
    ax2.bar(positions + width / 2, metric_table["mean_rmse_10y"], width=width, color="#54a24b", label="Rolling 10y mean RMSE")
    ax2.set_xticks(positions)
    ax2.set_xticklabels(metric_table.index, rotation=25, ha="right")
    ax2.set_ylabel("RMSE (m)")
    ax2.grid(axis="y", alpha=0.25)
    ax2.legend(fontsize=9)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_summary_markdown(
    summaries: pd.DataFrame,
    backtests: pd.DataFrame,
    *,
    selected_model: str,
    trend_beaten: bool,
    output_path: Path,
) -> None:
    baseline = summaries[summaries["model"] == "baseline_trend"]
    selected = summaries[summaries["model"] == selected_model]
    lines = [
        "# Sojs Annual Model Summary",
        "",
        f"**Selected annual projection model:** `{selected_model}`",
        "**Target:** Portland annual mean relative sea level with deterministic land-motion adjustment applied in target space.",
        "**Prediction interval:** 80% Gaussian band using in-sample residual sigma for backtest coverage.",
        "",
        "## Model ladder summary",
        "",
        "| Model | Years | Start | End | Mean RMSE 5y | Mean RMSE 10y | Tail RMSE 10y | Mean 80% coverage |",
        "|-------|------:|------:|----:|-------------:|--------------:|--------------:|------------------:|",
    ]
    for _, row in summaries.iterrows():
        lines.append(
            f"| {row['model']} | {int(row['n_years'])} | {int(row['time_start_year'])} | {int(row['time_end_year'])} "
            f"| {row['mean_rmse_5y']:.5f} | {row['mean_rmse_10y']:.5f} | {row['tail_rmse_10y']:.5f} "
            f"| {row['mean_interval_coverage_80']:.3f} |"
        )

    lines += [
        "",
        "## Readout",
        "",
        f"- Trend-only beaten on rolling 5-year holdouts: {'yes' if trend_beaten else 'no'}",
        f"- Trend-only 5-year mean RMSE: {float(baseline['mean_rmse_5y'].iloc[0]):.5f}" if not baseline.empty else "- Trend-only 5-year mean RMSE: n/a",
        f"- Selected-model 5-year mean RMSE: {float(selected['mean_rmse_5y'].iloc[0]):.5f}" if not selected.empty else "- Selected-model 5-year mean RMSE: n/a",
        "- Rolling-origin evaluation includes both 5-year and 10-year holdouts plus a final contiguous 10-year tail holdout.",
        "- NAO joins provide the long historical annual driver family. Copernicus SLA and Greenland mass only enter where their annual coverage supports them.",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def save_model_json(
    fit: dict[str, object],
    *,
    spec: ModelSpec,
    bootstrap_coefficients: np.ndarray,
    training_years: np.ndarray,
    training_target_adjusted: np.ndarray,
    training_fitted_adjusted: np.ndarray,
    output_path: Path,
) -> None:
    trend_time = years_since_origin(training_years.astype(int), int(fit["origin_year"]))
    observed_trend_slope, observed_trend_intercept = np.polyfit(
        trend_time,
        training_target_adjusted,
        1,
    )
    payload = {
        "model_name": spec.name,
        "predictors": list(spec.predictors),
        "use_ridge": bool(spec.use_ridge),
        "ridge_lambda": float(spec.ridge_lambda if spec.use_ridge else 0.0),
        "origin_year": int(fit["origin_year"]),
        "coefficients": np.asarray(fit["coefficients"], dtype=float).tolist(),
        "predictor_means": fit["predictor_means"],
        "predictor_stds": fit["predictor_stds"],
        "residual_sigma_m": float(fit["residual_sigma_m"]),
        "target_baseline_m": float(fit["target_baseline_m"]),
        "relative_land_motion_mm_yr": float(fit["relative_land_motion_mm_yr"]),
        "relative_land_motion_sigma_mm_yr": float(fit["relative_land_motion_sigma_mm_yr"]),
        "land_motion_reference_year": int(fit["land_motion_reference_year"]),
        "land_motion_reference_mean_m": float(fit["land_motion_reference_mean_m"]),
        "land_motion_kind": str(fit["land_motion_kind"]),
        "land_motion_source": str(fit["land_motion_source"]),
        "train_years": fit["train_years"],
        "training_target_adjusted_m": training_target_adjusted.tolist(),
        "training_fitted_adjusted_m": training_fitted_adjusted.tolist(),
        "training_residuals_m": (training_target_adjusted - training_fitted_adjusted).tolist(),
        "observed_target_trend_slope_m_per_year": float(observed_trend_slope),
        "observed_target_trend_intercept_m": float(observed_trend_intercept),
        "bootstrap_coefficients": bootstrap_coefficients.tolist(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)

    specs = [
        ModelSpec(spec.name, spec.predictors, spec.use_ridge, args.ridge_lambda if spec.use_ridge else spec.ridge_lambda)
        for spec in MODEL_SPECS
    ]
    frame = load_training_frame(args.training_path)

    all_backtests: list[pd.DataFrame] = []
    summary_rows: list[dict[str, float]] = []
    for spec in specs:
        results, summary = evaluate_spec(frame, spec, min_train_years=args.min_train_years)
        if not results.empty:
            all_backtests.append(results)
        if summary:
            summary_rows.append(summary)

    if not summary_rows:
        raise SystemExit("No annual model backtests could be run with the available data.")

    backtests = pd.concat(all_backtests, ignore_index=True) if all_backtests else pd.DataFrame()
    summaries = pd.DataFrame(summary_rows).sort_values("mean_rmse_5y", kind="stable")
    selected_model = select_final_model(summaries)
    selected_spec = next(spec for spec in specs if spec.name == selected_model)
    selected_working = prepare_model_frame(frame, selected_spec)
    selected_fit = fit_linear_model(selected_working, selected_spec)
    selected_training_years = selected_working["year"].to_numpy(dtype=int)
    selected_training_target = selected_working["portland_target_adjusted_m"].to_numpy(dtype=float)
    selected_training_fitted = predict_linear_model(selected_fit, selected_working)
    bootstrap_coeffs, _ = fit_bootstrap_coefficients(
        selected_working,
        selected_spec,
        n_bootstraps=args.bootstraps,
    )

    baseline_rmse = float(
        summaries.loc[summaries["model"] == "baseline_trend", "mean_rmse_5y"].iloc[0]
    )
    selected_rmse = float(
        summaries.loc[summaries["model"] == selected_model, "mean_rmse_5y"].iloc[0]
    )
    trend_beaten = bool(selected_rmse < baseline_rmse)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.plot_dir.mkdir(parents=True, exist_ok=True)
    backtests.to_csv(
        args.output_dir / "sojs_portland_annual_backtest.csv",
        index=False,
        float_format="%.6f",
    )
    save_model_json(
        selected_fit,
        spec=selected_spec,
        bootstrap_coefficients=bootstrap_coeffs,
        training_years=selected_training_years,
        training_target_adjusted=selected_training_target,
        training_fitted_adjusted=selected_training_fitted,
        output_path=args.output_dir / MODEL_JSON_NAME,
    )
    save_backtest_plot(
        frame,
        summaries,
        selected_fit,
        selected_spec,
        args.plot_dir / "portland_annual_backtest.png",
    )
    save_summary_markdown(
        summaries,
        backtests,
        selected_model=selected_model,
        trend_beaten=trend_beaten,
        output_path=args.plot_dir / "sojs_annual_model_summary.md",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
