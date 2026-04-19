from __future__ import annotations

import argparse
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

from hindcast_model import (
    DEFAULT_N_SPLITS,
    DEFAULT_RIDGE_LAMBDA,
    EXTERNAL_PREDICTORS,
    FINAL_MODEL,
    STATIONS,
    evaluate_station,
    extrapolate_target_with_final_model,
    fit_station_final_model,
    gia_adjustment_with_reference,
    load_frame,
    predict_with_final_model,
    skill_metrics,
)
from normalize_active_data import load_grace_series


DEFAULT_NORMALIZED_PATH = Path("data/normalized/sojs_active_monthly_normalized.nc")
DEFAULT_GRACE_CONTINUATION_PATH = Path("data/grace/grace_ocean_mass_monthly.nc")
DEFAULT_OUTPUT_DIR = Path("data/predictions")
DEFAULT_PLOT_DIR = Path("plots/predictions")
DEFAULT_GOM_MIN_LON = -72.0
DEFAULT_GOM_MAX_LON = -64.0
DEFAULT_GOM_MIN_LAT = 41.0
DEFAULT_GOM_MAX_LAT = 48.0

REGIME_LABELS = {
    1: "constrained_reconstruction",
    2: "validated_continuation",
    3: "pure_extrapolation",
}
REGIME_CODES = {label: code for code, label in REGIME_LABELS.items()}
REGIME_COLORS = {
    "constrained_reconstruction": "#cfe8cf",
    "validated_continuation": "#fde0c5",
    "pure_extrapolation": "#e0e0e0",
}
MODEL_READY_REGIMES = {"constrained_reconstruction", "validated_continuation"}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build monthly Sojs station predictions from the validated Phase 4 final model, "
            "attach regime labels, and export monthly plus annual summaries."
        )
    )
    parser.add_argument("--normalized", type=Path, default=DEFAULT_NORMALIZED_PATH)
    parser.add_argument(
        "--grace-continuation",
        type=Path,
        default=DEFAULT_GRACE_CONTINUATION_PATH,
        help="GRACE-FO continuation grid used for the post-2017 same-family mass term.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--ridge-lambda", type=float, default=DEFAULT_RIDGE_LAMBDA)
    parser.add_argument("--n-splits", type=int, default=DEFAULT_N_SPLITS)
    parser.add_argument("--future-months", type=int, default=0)
    parser.add_argument("--gom-min-lon", type=float, default=DEFAULT_GOM_MIN_LON)
    parser.add_argument("--gom-max-lon", type=float, default=DEFAULT_GOM_MAX_LON)
    parser.add_argument("--gom-min-lat", type=float, default=DEFAULT_GOM_MIN_LAT)
    parser.add_argument("--gom-max-lat", type=float, default=DEFAULT_GOM_MAX_LAT)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.gom_min_lon >= args.gom_max_lon:
        raise SystemExit("--gom-min-lon must be smaller than --gom-max-lon.")
    if args.gom_min_lat >= args.gom_max_lat:
        raise SystemExit("--gom-min-lat must be smaller than --gom-max-lat.")
    if args.future_months < 0:
        raise SystemExit("--future-months must be zero or greater.")


def load_grace_continuation(args: argparse.Namespace) -> pd.Series:
    if not args.grace_continuation.exists():
        raise SystemExit(f"GRACE continuation dataset not found: {args.grace_continuation}")
    return load_grace_series(
        args.grace_continuation,
        variable_name="lwe_thickness",
        output_name="grace_fo_lwe_thickness_gom_m",
        min_lat=args.gom_min_lat,
        max_lat=args.gom_max_lat,
        min_lon=args.gom_min_lon,
        max_lon=args.gom_max_lon,
    )


def extended_prediction_index(
    frame: pd.DataFrame,
    continuation: pd.Series,
    *,
    future_months: int,
) -> pd.DatetimeIndex:
    start = frame.loc[frame["is_argo_overlap_month"] == 1].index.min()
    if pd.isna(start):
        raise SystemExit("No Argo-overlap start month was found in the normalized dataset.")
    end_candidates = [
        frame.index.max(),
        continuation.index.max(),
    ]
    end = max(ts for ts in end_candidates if not pd.isna(ts))
    if future_months:
        end = end + pd.DateOffset(months=future_months)
    return pd.date_range(start=start, end=end, freq="MS")


def build_model_inputs(
    frame: pd.DataFrame,
    continuation_raw: pd.Series,
    full_index: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    historical_mass = frame["grace_hist_lwe_thickness_gom_m"].dropna()
    hist_mean = float(historical_mass.mean())
    hist_std = float(historical_mass.std(ddof=0))
    continuation_z = (
        (continuation_raw - hist_mean) / hist_std if hist_std > 0.0 else continuation_raw * np.nan
    )

    predictors = pd.DataFrame(index=full_index)
    for name in EXTERNAL_PREDICTORS:
        predictors[name] = frame[name].reindex(full_index)
    predictors["grace_hist_lwe_thickness_gom_m_zscore"] = (
        frame["grace_hist_lwe_thickness_gom_m_zscore"]
        .reindex(full_index)
        .combine_first(continuation_z.reindex(full_index))
    )
    predictors["argo_density_shelf_0_200dbar_kg_m3_zscore"] = frame[
        "argo_density_shelf_0_200dbar_kg_m3_zscore"
    ].reindex(full_index)

    mass_source = pd.Series("unavailable", index=full_index, dtype="object")
    historical_present = frame["grace_hist_lwe_thickness_gom_m_zscore"].reindex(full_index).notna()
    continuation_present = continuation_z.reindex(full_index).notna()
    mass_source.loc[historical_present] = "historical_grace"
    mass_source.loc[~historical_present & continuation_present] = "grace_fo_continuation"
    return predictors, continuation_z.reindex(full_index), mass_source


def build_regime_labels(
    frame: pd.DataFrame,
    predictors: pd.DataFrame,
    continuation_z: pd.Series,
    full_index: pd.DatetimeIndex,
) -> pd.Series:
    regime = pd.Series("pure_extrapolation", index=full_index, dtype="object")
    historical_ready = frame[
        [
            "copernicus_sla_gom_m_zscore",
            "grace_hist_lwe_thickness_gom_m_zscore",
            "greenland_mass_gt_zscore",
            "argo_density_shelf_0_200dbar_kg_m3_zscore",
        ]
    ].reindex(full_index).notna().all(axis=1)
    continuation_ready = predictors.notna().all(axis=1)
    continuation_only = (
        frame["grace_hist_lwe_thickness_gom_m_zscore"].reindex(full_index).isna()
        & continuation_z.notna()
    )

    regime.loc[historical_ready] = "constrained_reconstruction"
    regime.loc[continuation_ready & continuation_only] = "validated_continuation"
    return regime


def load_station_uncertainty(
    frame: pd.DataFrame,
    *,
    ridge_lambda: float | None,
    n_splits: int,
) -> dict[str, float]:
    uncertainties: dict[str, float] = {}
    for station_name, config in STATIONS.items():
        _, summaries = evaluate_station(
            frame,
            station_name=station_name,
            station_variable=config["variable"],
            gia_rate_mm_yr=float(config["gia_rate_mm_yr"]),
            n_splits=n_splits,
            ridge_lambda=ridge_lambda,
        )
        final_row = next(row for row in summaries if row["model"] == FINAL_MODEL)
        uncertainties[station_name] = float(final_row["rmse_m"])
    return uncertainties


def build_station_prediction_frame(
    frame: pd.DataFrame,
    predictors: pd.DataFrame,
    regime: pd.Series,
    mass_source: pd.Series,
    *,
    station_name: str,
    station_variable: str,
    gia_rate_mm_yr: float,
    ridge_lambda: float | None,
    prediction_rmse_m: float,
) -> pd.DataFrame:
    _, fit = fit_station_final_model(
        frame,
        station_name=station_name,
        station_variable=station_variable,
        gia_rate_mm_yr=gia_rate_mm_yr,
        ridge_lambda=ridge_lambda,
    )

    output = pd.DataFrame(index=predictors.index)
    output["station_name"] = station_name
    output["regime_label"] = regime
    output["regime_code"] = regime.map(REGIME_CODES).astype(np.int8)
    output["mass_source"] = mass_source

    predicted_target_adjusted = pd.Series(np.nan, index=output.index, dtype=float)
    predicted_target_deseasoned = pd.Series(np.nan, index=output.index, dtype=float)

    model_mask = output["regime_label"].isin(MODEL_READY_REGIMES)
    if model_mask.any():
        ready_index = output.index[model_mask]
        y_pred, y_pred_ds = predict_with_final_model(
            fit,
            ready_index,
            predictors.loc[ready_index, list(fit.predictor_names)].to_numpy(dtype=float),
        )
        predicted_target_adjusted.loc[ready_index] = y_pred
        predicted_target_deseasoned.loc[ready_index] = y_pred_ds

    extrap_index = output.index[~model_mask]
    if len(extrap_index) > 0:
        y_pred, y_pred_ds = extrapolate_target_with_final_model(fit, extrap_index)
        predicted_target_adjusted.loc[extrap_index] = y_pred
        predicted_target_deseasoned.loc[extrap_index] = y_pred_ds

    gia_component = gia_adjustment_with_reference(
        output.index,
        gia_rate_mm_yr,
        origin=fit.time_origin,
        reference_mean_m=fit.gia_reference_mean_m,
    )
    predicted_anomaly = predicted_target_adjusted.to_numpy(dtype=float) + gia_component
    predicted_absolute = predicted_anomaly + fit.target_baseline_m

    observed = frame.reindex(output.index)
    observed_anomaly = observed[f"{station_variable}_anomaly"]
    observed_absolute = observed[station_variable]

    output["station_baseline_m"] = fit.target_baseline_m
    output["gia_component_m"] = gia_component
    output["predicted_target_adjusted_m"] = predicted_target_adjusted.to_numpy(dtype=float)
    output["predicted_target_deseasoned_m"] = predicted_target_deseasoned.to_numpy(dtype=float)
    output["predicted_anomaly_m"] = predicted_anomaly
    output["predicted_m"] = predicted_absolute
    output["predicted_lower_1sigma_m"] = predicted_absolute - prediction_rmse_m
    output["predicted_upper_1sigma_m"] = predicted_absolute + prediction_rmse_m
    output["prediction_rmse_m"] = prediction_rmse_m
    output["observed_m"] = observed_absolute.to_numpy(dtype=float)
    output["observed_anomaly_m"] = observed_anomaly.to_numpy(dtype=float)
    output["observed_target_adjusted_m"] = observed_anomaly.to_numpy(dtype=float) - gia_component
    output["residual_m"] = output["observed_m"] - output["predicted_m"]
    output["has_observation"] = output["observed_m"].notna().astype(np.int8)

    return output.reset_index().rename(columns={"index": "time"})


def build_annual_summary(monthly: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    working = monthly.copy()
    working["year"] = pd.to_datetime(working["time"]).dt.year
    for (station_name, year), group in working.groupby(["station_name", "year"], sort=True):
        predicted = group["predicted_m"].dropna()
        if predicted.empty:
            continue
        observed = group["observed_m"].dropna()
        residual = group["residual_m"].dropna()
        regimes = sorted(group["regime_label"].dropna().unique())
        rows.append(
            {
                "station_name": station_name,
                "year": int(year),
                "months_with_predictions": int(predicted.shape[0]),
                "months_with_observations": int(observed.shape[0]),
                "is_complete_prediction_year": int(predicted.shape[0] == 12),
                "regime_label": regimes[0] if len(regimes) == 1 else "mixed",
                "predicted_mean_m": float(predicted.mean()),
                "observed_mean_m": float(observed.mean()) if not observed.empty else np.nan,
                "mean_residual_m": float(residual.mean()) if not residual.empty else np.nan,
                "prediction_rmse_m": float(group["prediction_rmse_m"].iloc[0]),
            }
        )
    return pd.DataFrame(rows)


def build_validation_summary(monthly: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    observed = monthly.dropna(subset=["observed_m", "predicted_m"]).copy()
    for (station_name, regime_label), group in observed.groupby(["station_name", "regime_label"], sort=True):
        metrics = skill_metrics(
            group["observed_m"].to_numpy(dtype=float),
            group["predicted_m"].to_numpy(dtype=float),
        )
        rows.append(
            {
                "station_name": station_name,
                "regime_label": regime_label,
                "time_start": pd.to_datetime(group["time"]).min().strftime("%Y-%m-%d"),
                "time_end": pd.to_datetime(group["time"]).max().strftime("%Y-%m-%d"),
                "observed_months": int(group.shape[0]),
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def regime_segments(monthly: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, str]]:
    ordered = monthly.sort_values("time")[["time", "regime_label"]].drop_duplicates()
    segments: list[tuple[pd.Timestamp, pd.Timestamp, str]] = []
    current_label = str(ordered.iloc[0]["regime_label"])
    start = pd.Timestamp(ordered.iloc[0]["time"])
    previous = start
    for _, row in ordered.iloc[1:].iterrows():
        current_time = pd.Timestamp(row["time"])
        label = str(row["regime_label"])
        if label != current_label:
            segments.append((start, previous, current_label))
            start = current_time
            current_label = label
        previous = current_time
    segments.append((start, previous, current_label))
    return segments


def save_station_plot(monthly: pd.DataFrame, path: Path) -> None:
    station_name = str(monthly["station_name"].iloc[0])
    ordered = monthly.sort_values("time")
    index = pd.to_datetime(ordered["time"])
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

    for start, end, label in regime_segments(ordered):
        span_end = end + pd.offsets.MonthEnd(1)
        color = REGIME_COLORS[label]
        ax1.axvspan(start, span_end, color=color, alpha=0.35, linewidth=0.0)
        ax2.axvspan(start, span_end, color=color, alpha=0.35, linewidth=0.0)

    ax1.fill_between(
        index,
        ordered["predicted_lower_1sigma_m"].to_numpy(dtype=float),
        ordered["predicted_upper_1sigma_m"].to_numpy(dtype=float),
        color="#f58518",
        alpha=0.18,
        label="Prediction +/- 1 CV RMSE",
    )
    ax1.plot(index, ordered["predicted_m"], color="#f58518", linewidth=1.5, label="Predicted")
    ax1.plot(index, ordered["observed_m"], color="#2f4b7c", linewidth=1.2, label="Observed")
    ax1.set_ylabel("Sea level (m)")
    ax1.set_title(f"{station_name}: monthly Sojs prediction by regime")
    ax1.grid(alpha=0.25)
    ax1.legend(loc="upper left", fontsize=9)

    ax2.plot(index, ordered["residual_m"], color="#54a24b", linewidth=1.2)
    ax2.axhline(0.0, color="black", linewidth=0.8, alpha=0.7)
    ax2.set_ylabel("Residual (m)")
    ax2.set_xlabel("Time")
    ax2.set_title("Observed minus predicted")
    ax2.grid(alpha=0.25)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_monthly_dataset(monthly: pd.DataFrame, output_path: Path) -> None:
    numeric_columns = [
        "regime_code",
        "station_baseline_m",
        "gia_component_m",
        "predicted_target_adjusted_m",
        "predicted_target_deseasoned_m",
        "predicted_anomaly_m",
        "predicted_m",
        "predicted_lower_1sigma_m",
        "predicted_upper_1sigma_m",
        "prediction_rmse_m",
        "observed_m",
        "observed_anomaly_m",
        "observed_target_adjusted_m",
        "residual_m",
        "has_observation",
    ]
    ds = (
        monthly[["time", "station_name", *numeric_columns]]
        .set_index(["time", "station_name"])
        .to_xarray()
        .transpose("station_name", "time", ...)
    )
    ds["regime_code"].attrs.update(
        {
            "flag_values": list(REGIME_LABELS),
            "flag_meanings": " ".join(REGIME_LABELS[code] for code in sorted(REGIME_LABELS)),
        }
    )
    ds.attrs.update(
        {
            "title": "Sojs monthly station predictions",
            "description": (
                "Monthly Portland and Bar Harbor predictions from the Sojs Phase 4 final model. "
                "Regime A uses the historical validated predictor stack, Regime B swaps in the "
                "same-family GRACE-FO mass continuation, and Regime C is a trend-plus-seasonal "
                "extrapolation when the full predictor stack is unavailable."
            ),
            "final_model": FINAL_MODEL,
            "published_stations": ", ".join(STATIONS),
            "excluded_station": "Rockland",
            "excluded_station_reason": (
                "Rockland remains outside the validated monthly modeling window until a modern "
                "target series is added deliberately."
            ),
            "uncertainty_definition": "station-specific Phase 4 cross-validation RMSE carried forward as +/- 1 sigma",
            "regime_mapping": ", ".join(f"{code}={label}" for code, label in REGIME_LABELS.items()),
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoding: dict[str, dict[str, object]] = {}
    for name, data_array in ds.data_vars.items():
        if np.issubdtype(data_array.dtype, np.floating):
            encoding[name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
        else:
            encoding[name] = {"zlib": True, "complevel": 4}
    ds.to_netcdf(output_path, encoding=encoding)
    ds.close()


def save_summary_markdown(
    monthly: pd.DataFrame,
    validation: pd.DataFrame,
    output_path: Path,
) -> None:
    lines = [
        "# Sojs Monthly Prediction Summary",
        "",
        f"**Final model:** `{FINAL_MODEL}`",
        "**Scope:** Portland and Bar Harbor only. Rockland is intentionally excluded.",
        "**Uncertainty:** station-specific Phase 4 cross-validation RMSE carried forward as a constant +/- 1 sigma band.",
        "",
        "## Regime windows",
        "",
    ]
    first_station = monthly[monthly["station_name"] == monthly["station_name"].iloc[0]]
    for start, end, label in regime_segments(first_station):
        lines.append(f"- `{label}`: {start.strftime('%Y-%m')} to {end.strftime('%Y-%m')}")
    lines += [
        "",
        "## Observed-period validation",
        "",
        "| Station | Regime | Months | RMSE (m) | MAE (m) | Bias (m) | R^2 |",
        "|---------|--------|--------|----------|---------|----------|-----|",
    ]
    for _, row in validation.iterrows():
        lines.append(
            f"| {row['station_name']} | {row['regime_label']} | {int(row['observed_months'])} "
            f"| {row['rmse_m']:.5f} | {row['mae_m']:.5f} | {row['bias_m']:.5f} | {row['r_squared']:.4f} |"
        )
    lines += [
        "",
        "## Notes",
        "",
        "- Regime A is observationally constrained by the full validated predictor stack.",
        "- Regime B keeps Argo in the final model and swaps in GRACE-FO as the same-family ocean-mass continuation.",
        "- Regime C is explicitly extrapolative and should not be interpreted as a model-constrained closure estimate.",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)
    if not args.normalized.exists():
        raise SystemExit(f"Normalized dataset not found: {args.normalized}")

    ridge_lambda: float | None = args.ridge_lambda if args.ridge_lambda != 0.0 else None
    frame = load_frame(args.normalized)
    continuation_raw = load_grace_continuation(args)
    full_index = extended_prediction_index(frame, continuation_raw, future_months=args.future_months)
    predictors, continuation_z, mass_source = build_model_inputs(frame, continuation_raw, full_index)
    regime = build_regime_labels(frame, predictors, continuation_z, full_index)
    uncertainties = load_station_uncertainty(frame, ridge_lambda=ridge_lambda, n_splits=args.n_splits)

    monthly_frames: list[pd.DataFrame] = []
    for station_name, config in STATIONS.items():
        monthly_frames.append(
            build_station_prediction_frame(
                frame,
                predictors,
                regime,
                mass_source,
                station_name=station_name,
                station_variable=config["variable"],
                gia_rate_mm_yr=float(config["gia_rate_mm_yr"]),
                ridge_lambda=ridge_lambda,
                prediction_rmse_m=uncertainties[station_name],
            )
        )

    monthly = pd.concat(monthly_frames, ignore_index=True)
    annual = build_annual_summary(monthly)
    validation = build_validation_summary(monthly)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.plot_dir.mkdir(parents=True, exist_ok=True)

    monthly.to_csv(args.output_dir / "sojs_monthly_predictions.csv", index=False, float_format="%.6f")
    annual.to_csv(args.output_dir / "sojs_annual_prediction_summary.csv", index=False, float_format="%.6f")
    validation.to_csv(
        args.output_dir / "sojs_prediction_validation_summary.csv",
        index=False,
        float_format="%.6f",
    )
    save_monthly_dataset(monthly, args.output_dir / "sojs_monthly_predictions.nc")
    save_summary_markdown(monthly, validation, args.plot_dir / "sojs_prediction_summary.md")

    for station_name in monthly["station_name"].unique():
        safe = station_name.lower().replace(" ", "_")
        save_station_plot(
            monthly[monthly["station_name"] == station_name],
            args.plot_dir / f"{safe}_monthly_prediction.png",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
