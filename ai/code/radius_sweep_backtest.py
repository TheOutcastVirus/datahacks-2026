"""Run matched rolling backtests across multiple CalCOFI radii.

This script tests whether temperature and salinity add value beyond persistence
for La Jolla sea level prediction, while holding the evaluation subset fixed
within each radius and using repeated chronological folds.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from compare_coops_calcofi_features import build_feature_table, fit_ols


RADII_DEG = [1.0, 1.5, 3.0, 5.0]
MIN_TRAIN_ROWS = 72
TEST_WINDOW_ROWS = 12
STEP_ROWS = 12

MATCHED_MODELS = [
    ("persistence", ["persistence_1"]),
    ("persistence_temp_now", ["persistence_1", "temp_anomaly"]),
    (
        "persistence_temp_salinity_now",
        ["persistence_1", "temp_anomaly", "salinity_anomaly"],
    ),
    (
        "persistence_temp_lags",
        ["persistence_1", "temp_anomaly", "temp_anomaly_lag_1", "temp_anomaly_lag_3"],
    ),
    (
        "persistence_temp_salinity_lags",
        [
            "persistence_1",
            "temp_anomaly",
            "temp_anomaly_lag_1",
            "temp_anomaly_lag_3",
            "salinity_anomaly",
            "salinity_anomaly_lag_1",
            "salinity_anomaly_lag_3",
        ],
    ),
]


T_CRIT_975 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def build_shared_subset(
    df: pd.DataFrame,
    model_specs: list[tuple[str, list[str]]],
    target_col: str = "sea_level_anomaly",
) -> pd.DataFrame:
    required_cols = sorted(
        {target_col, *(feature for _, features in model_specs for feature in features)}
    )
    shared = df[required_cols].dropna().copy()
    if len(shared) < MIN_TRAIN_ROWS + TEST_WINDOW_ROWS:
        raise ValueError(
            "Not enough complete rows for rolling backtest: "
            f"found {len(shared)}, need at least {MIN_TRAIN_ROWS + TEST_WINDOW_ROWS}."
        )
    return shared


def rolling_folds(df: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame, int]]:
    folds: list[tuple[pd.DataFrame, pd.DataFrame, int]] = []
    train_end = MIN_TRAIN_ROWS
    fold_id = 1
    while train_end + TEST_WINDOW_ROWS <= len(df):
        train_df = df.iloc[:train_end].copy()
        test_df = df.iloc[train_end : train_end + TEST_WINDOW_ROWS].copy()
        folds.append((train_df, test_df, fold_id))
        train_end += STEP_ROWS
        fold_id += 1
    return folds


def evaluate_radius(radius_deg: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    df, profile_count = build_feature_table(radius_deg)
    shared = build_shared_subset(df, MATCHED_MODELS)
    folds = rolling_folds(shared)

    fold_rows: list[dict[str, object]] = []
    for train_df, test_df, fold_id in folds:
        for model_name, features in MATCHED_MODELS:
            metrics = fit_ols(train_df, test_df, features)
            fold_rows.append(
                {
                    "radius_deg": radius_deg,
                    "profiles": profile_count,
                    "shared_rows": len(shared),
                    "fold": fold_id,
                    "model": model_name,
                    "train_start": train_df.index.min().strftime("%Y-%m"),
                    "train_end": train_df.index.max().strftime("%Y-%m"),
                    "test_start": test_df.index.min().strftime("%Y-%m"),
                    "test_end": test_df.index.max().strftime("%Y-%m"),
                    "rmse": metrics["rmse"],
                    "mae": metrics["mae"],
                    "r2": metrics["r2"],
                }
            )

    fold_df = pd.DataFrame(fold_rows)
    summary = (
        fold_df.groupby(["radius_deg", "profiles", "shared_rows", "model"], as_index=False)
        .agg(
            folds=("fold", "nunique"),
            mean_rmse=("rmse", "mean"),
            std_rmse=("rmse", "std"),
            mean_mae=("mae", "mean"),
            mean_r2=("r2", "mean"),
        )
        .sort_values(["radius_deg", "mean_rmse", "model"])
        .reset_index(drop=True)
    )
    return summary, fold_df


def incremental_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for radius in sorted(summary_df["radius_deg"].unique()):
        subset = summary_df[summary_df["radius_deg"] == radius].set_index("model")
        base = subset.loc["persistence"]
        temp_now = subset.loc["persistence_temp_now"]
        temp_sal_now = subset.loc["persistence_temp_salinity_now"]
        temp_lags = subset.loc["persistence_temp_lags"]
        temp_sal_lags = subset.loc["persistence_temp_salinity_lags"]
        rows.append(
            {
                "radius_deg": radius,
                "shared_rows": int(base["shared_rows"]),
                "folds": int(base["folds"]),
                "profiles": int(base["profiles"]),
                "delta_rmse_temp_vs_persistence": temp_now["mean_rmse"] - base["mean_rmse"],
                "delta_rmse_temp_sal_vs_temp": temp_sal_now["mean_rmse"] - temp_now["mean_rmse"],
                "delta_rmse_temp_lags_vs_persistence": temp_lags["mean_rmse"] - base["mean_rmse"],
                "delta_rmse_temp_sal_lags_vs_temp_lags": temp_sal_lags["mean_rmse"] - temp_lags["mean_rmse"],
            }
        )
    return pd.DataFrame(rows).sort_values("radius_deg").reset_index(drop=True)


def t_critical_95(n: int) -> float:
    if n <= 1:
        return np.nan
    df = n - 1
    return T_CRIT_975.get(df, 1.96)


def fold_delta_tables(fold_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    delta_specs = [
        ("delta_rmse_temp_vs_persistence", "persistence_temp_now", "persistence"),
        (
            "delta_rmse_temp_sal_vs_temp",
            "persistence_temp_salinity_now",
            "persistence_temp_now",
        ),
        ("delta_rmse_temp_lags_vs_persistence", "persistence_temp_lags", "persistence"),
        (
            "delta_rmse_temp_sal_lags_vs_temp_lags",
            "persistence_temp_salinity_lags",
            "persistence_temp_lags",
        ),
    ]

    fold_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for radius in sorted(fold_df["radius_deg"].unique()):
        subset = fold_df[fold_df["radius_deg"] == radius]
        pivot = subset.pivot(index="fold", columns="model", values="rmse")
        shared_rows = int(subset["shared_rows"].iloc[0])
        profiles = int(subset["profiles"].iloc[0])

        for fold_id, row in pivot.iterrows():
            fold_row: dict[str, object] = {
                "radius_deg": radius,
                "profiles": profiles,
                "shared_rows": shared_rows,
                "fold": int(fold_id),
            }
            for delta_name, left_model, right_model in delta_specs:
                fold_row[delta_name] = float(row[left_model] - row[right_model])
            fold_rows.append(fold_row)

        for delta_name, left_model, right_model in delta_specs:
            deltas = (pivot[left_model] - pivot[right_model]).to_numpy(dtype=float)
            n = len(deltas)
            mean_delta = float(deltas.mean())
            std_delta = float(deltas.std(ddof=1)) if n > 1 else np.nan
            se_delta = float(std_delta / np.sqrt(n)) if n > 1 else np.nan
            margin = float(t_critical_95(n) * se_delta) if n > 1 else np.nan

            summary_rows.append(
                {
                    "radius_deg": radius,
                    "profiles": profiles,
                    "shared_rows": shared_rows,
                    "folds": n,
                    "comparison": delta_name,
                    "mean_delta_rmse": mean_delta,
                    "std_delta_rmse": std_delta,
                    "ci95_low": mean_delta - margin if n > 1 else np.nan,
                    "ci95_high": mean_delta + margin if n > 1 else np.nan,
                    "improved_folds": int((deltas < 0).sum()),
                    "worse_folds": int((deltas > 0).sum()),
                    "tied_folds": int((deltas == 0).sum()),
                }
            )

    fold_delta_df = pd.DataFrame(fold_rows).sort_values(["radius_deg", "fold"]).reset_index(drop=True)
    fold_delta_summary_df = (
        pd.DataFrame(summary_rows)
        .sort_values(["radius_deg", "comparison"])
        .reset_index(drop=True)
    )
    return fold_delta_df, fold_delta_summary_df


def main() -> None:
    all_summaries = []
    all_folds = []

    for radius in RADII_DEG:
        summary_df, fold_df = evaluate_radius(radius)
        all_summaries.append(summary_df)
        all_folds.append(fold_df)

    summary = pd.concat(all_summaries, ignore_index=True)
    fold_results = pd.concat(all_folds, ignore_index=True)
    deltas = incremental_summary(summary)
    fold_deltas, fold_delta_summary = fold_delta_tables(fold_results)

    print("Rolling matched backtest")
    print(
        f"Settings: min_train_rows={MIN_TRAIN_ROWS}, "
        f"test_window_rows={TEST_WINDOW_ROWS}, step_rows={STEP_ROWS}"
    )
    print()
    print("Mean metrics by radius and model:")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()
    print("Incremental RMSE summary (negative is better):")
    print(deltas.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
    print()

    print("Fold-level RMSE deltas by radius and fold (negative is better):")
    print(fold_deltas.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
    print()

    print("Fold-level RMSE delta summary with 95% confidence intervals:")
    print(
        fold_delta_summary.to_string(
            index=False,
            float_format=lambda x: f"{x:+.4f}",
        )
    )
    print()

    best_by_radius = (
        summary.sort_values(["radius_deg", "mean_rmse", "model"])
        .groupby("radius_deg", as_index=False)
        .first()[["radius_deg", "model", "mean_rmse", "mean_r2", "shared_rows", "folds"]]
    )
    print("Best model by radius:")
    print(best_by_radius.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    best_by_model = (
        summary.sort_values(["model", "mean_rmse", "radius_deg"])
        .groupby("model", as_index=False)
        .first()[["model", "radius_deg", "mean_rmse", "mean_r2", "shared_rows", "folds"]]
    )
    print("Best radius by model:")
    print(best_by_model.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    print(
        f"Evaluated {len(fold_results)} model-fold combinations "
        f"across {fold_results['radius_deg'].nunique()} radii."
    )


if __name__ == "__main__":
    main()
