"""Compare La Jolla sea level models using nearby CalCOFI temp/salinity features.

The script builds monthly anomaly features from:
- CO-OPS La Jolla sea level NetCDF
- nearby CalCOFI surface temperature/salinity

It then evaluates simple OLS models on a chronological train/test split to answer:
- does salinity help beyond temperature?
- do lagged temp/salinity features help?
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from project_paths import PROCESSED_CALCOFI_NC, PROCESSED_COOPS_NC


LA_JOLLA_LAT = 32.867
LA_JOLLA_LON = -117.257
DEFAULT_RADIUS_DEG = 1.5
SURFACE_M = 10.0
TEST_FRACTION = 0.2


SEA_NC = PROCESSED_COOPS_NC
CALCOFI_NC = PROCESSED_CALCOFI_NC


def monthly_anomaly(series: pd.Series) -> pd.Series:
    climatology = series.groupby(series.index.month).transform("mean")
    return series - climatology


def load_sea_level() -> pd.DataFrame:
    with xr.open_dataset(SEA_NC) as ds:
        df = ds[["sea_level_anomaly"]].to_dataframe()
    return df.sort_index()


def load_calcofi(radius_deg: float) -> tuple[pd.DataFrame, int]:
    with xr.open_dataset(CALCOFI_NC, engine="netcdf4") as ds:
        distance = ((ds.lat - LA_JOLLA_LAT) ** 2 + (ds.lon - LA_JOLLA_LON) ** 2) ** 0.5
        mask = (distance < radius_deg).values
        subset = ds.isel(profile=mask)
        surface = subset.sel(depth=slice(0, SURFACE_M)).mean(dim="depth", skipna=True)

        df = (
            pd.DataFrame(
                {
                    "time": pd.to_datetime(subset.time.values),
                    "temp": surface.Temp.values,
                    "salinity": surface.Salinity.values,
                }
            )
            .dropna(how="all")
            .set_index("time")
            .sort_index()
            .resample("MS")
            .mean()
        )

    return df, int(mask.sum())


def build_feature_table(radius_deg: float) -> tuple[pd.DataFrame, int]:
    sea = load_sea_level()
    cal, profile_count = load_calcofi(radius_deg)

    overlap_start = max(sea.index.min(), cal.index.min())
    overlap_end = min(sea.index.max(), cal.index.max())
    monthly_index = pd.date_range(overlap_start, overlap_end, freq="MS")

    df = sea.reindex(monthly_index).join(cal.reindex(monthly_index), how="left")
    df.index.name = "time"

    df["temp_anomaly"] = monthly_anomaly(df["temp"])
    df["salinity_anomaly"] = monthly_anomaly(df["salinity"])

    for lag in (1, 3, 6):
        df[f"temp_anomaly_lag_{lag}"] = df["temp_anomaly"].shift(lag)
        df[f"salinity_anomaly_lag_{lag}"] = df["salinity_anomaly"].shift(lag)

    df["persistence_1"] = df["sea_level_anomaly"].shift(1)
    return df, profile_count


def fit_ols(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str = "sea_level_anomaly",
) -> dict[str, object]:
    x_train = train_df[feature_cols].to_numpy(dtype=float)
    y_train = train_df[target_col].to_numpy(dtype=float)
    x_test = test_df[feature_cols].to_numpy(dtype=float)
    y_test = test_df[target_col].to_numpy(dtype=float)

    mu = x_train.mean(axis=0)
    sigma = x_train.std(axis=0)
    sigma[sigma == 0] = 1.0

    x_train_std = (x_train - mu) / sigma
    x_test_std = (x_test - mu) / sigma

    x_train_design = np.column_stack([np.ones(len(x_train_std)), x_train_std])
    x_test_design = np.column_stack([np.ones(len(x_test_std)), x_test_std])

    coef, *_ = np.linalg.lstsq(x_train_design, y_train, rcond=None)
    pred = x_test_design @ coef

    rmse = float(np.sqrt(np.mean((pred - y_test) ** 2)))
    mae = float(np.mean(np.abs(pred - y_test)))
    ss_res = float(np.sum((pred - y_test) ** 2))
    ss_tot = float(np.sum((y_test - y_test.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan

    coefficients = {"intercept": float(coef[0])}
    for idx, name in enumerate(feature_cols, start=1):
        coefficients[name] = float(coef[idx])

    return {
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "coefficients": coefficients,
        "predictions": pred,
    }


def chronological_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_idx = max(1, int(len(df) * (1.0 - TEST_FRACTION)))
    if split_idx >= len(df):
        split_idx = len(df) - 1
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    return train_df, test_df


def evaluate_model(df: pd.DataFrame, name: str, features: list[str]) -> dict[str, object]:
    subset = df[["sea_level_anomaly", *features]].dropna().copy()
    if len(subset) < 24:
        raise ValueError(f"Model '{name}' does not have enough complete rows.")

    train_df, test_df = chronological_split(subset)
    metrics = fit_ols(train_df, test_df, features)

    return {
        "model": name,
        "features": ", ".join(features),
        "n_total": len(subset),
        "n_train": len(train_df),
        "n_test": len(test_df),
        "train_start": train_df.index.min().strftime("%Y-%m"),
        "train_end": train_df.index.max().strftime("%Y-%m"),
        "test_start": test_df.index.min().strftime("%Y-%m"),
        "test_end": test_df.index.max().strftime("%Y-%m"),
        "rmse": metrics["rmse"],
        "mae": metrics["mae"],
        "r2": metrics["r2"],
        "coefficients": metrics["coefficients"],
    }


def evaluate_models_on_shared_subset(
    df: pd.DataFrame,
    model_specs: list[tuple[str, list[str]]],
    target_col: str = "sea_level_anomaly",
) -> list[dict[str, object]]:
    required_cols = sorted(
        {target_col, *(feature for _, features in model_specs for feature in features)}
    )
    shared = df[required_cols].dropna().copy()
    if len(shared) < 24:
        raise ValueError("Shared comparison subset does not have enough complete rows.")

    train_df, test_df = chronological_split(shared)
    results = []
    for name, features in model_specs:
        metrics = fit_ols(train_df, test_df, features, target_col=target_col)
        results.append(
            {
                "model": name,
                "features": ", ".join(features),
                "n_total": len(shared),
                "n_train": len(train_df),
                "n_test": len(test_df),
                "train_start": train_df.index.min().strftime("%Y-%m"),
                "train_end": train_df.index.max().strftime("%Y-%m"),
                "test_start": test_df.index.min().strftime("%Y-%m"),
                "test_end": test_df.index.max().strftime("%Y-%m"),
                "rmse": metrics["rmse"],
                "mae": metrics["mae"],
                "r2": metrics["r2"],
                "coefficients": metrics["coefficients"],
            }
        )

    return results


def main() -> None:
    radius_deg = DEFAULT_RADIUS_DEG
    df, profile_count = build_feature_table(radius_deg)

    models = [
        ("persistence", ["persistence_1"]),
        ("temp_only_now", ["temp_anomaly"]),
        ("temp_salinity_now", ["temp_anomaly", "salinity_anomaly"]),
        ("temp_lags", ["temp_anomaly", "temp_anomaly_lag_1", "temp_anomaly_lag_3"]),
        (
            "temp_salinity_lags",
            [
                "temp_anomaly",
                "temp_anomaly_lag_1",
                "temp_anomaly_lag_3",
                "salinity_anomaly",
                "salinity_anomaly_lag_1",
                "salinity_anomaly_lag_3",
            ],
        ),
    ]

    results = [evaluate_model(df, name, features) for name, features in models]
    results_df = pd.DataFrame(results).drop(columns=["coefficients"])

    matched_models = [
        ("matched_persistence", ["persistence_1"]),
        ("matched_persistence_temp_now", ["persistence_1", "temp_anomaly"]),
        (
            "matched_persistence_temp_salinity_now",
            ["persistence_1", "temp_anomaly", "salinity_anomaly"],
        ),
        (
            "matched_persistence_temp_lags",
            ["persistence_1", "temp_anomaly", "temp_anomaly_lag_1", "temp_anomaly_lag_3"],
        ),
        (
            "matched_persistence_temp_salinity_lags",
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
    matched_results = evaluate_models_on_shared_subset(df, matched_models)
    matched_results_df = pd.DataFrame(matched_results).drop(columns=["coefficients"])

    print(f"Radius: {radius_deg:.1f} degrees")
    print(f"Surface averaging depth: {SURFACE_M:.0f} m")
    print(f"CalCOFI profiles included: {profile_count}")
    print(f"Sea level / CalCOFI overlap: {df.index.min().strftime('%Y-%m')} -> {df.index.max().strftime('%Y-%m')}")
    print()
    print("Unmatched comparison (different row counts by feature availability):")
    print(results_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()
    print("Matched comparison (same exact rows and test window for all models):")
    print(matched_results_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()

    temp_only = next(r for r in results if r["model"] == "temp_only_now")
    temp_sal = next(r for r in results if r["model"] == "temp_salinity_now")
    temp_lags = next(r for r in results if r["model"] == "temp_lags")
    temp_sal_lags = next(r for r in results if r["model"] == "temp_salinity_lags")
    matched_persist = next(r for r in matched_results if r["model"] == "matched_persistence")
    matched_temp = next(
        r for r in matched_results if r["model"] == "matched_persistence_temp_now"
    )
    matched_temp_sal = next(
        r
        for r in matched_results
        if r["model"] == "matched_persistence_temp_salinity_now"
    )
    matched_temp_lags = next(
        r for r in matched_results if r["model"] == "matched_persistence_temp_lags"
    )
    matched_temp_sal_lags = next(
        r
        for r in matched_results
        if r["model"] == "matched_persistence_temp_salinity_lags"
    )

    print("Incremental salinity test:")
    print(
        f"- Same-month model RMSE change (temp+salinity minus temp only): "
        f"{temp_sal['rmse'] - temp_only['rmse']:+.4f}"
    )
    print(
        f"- Lagged model RMSE change (temp+salinity lags minus temp lags): "
        f"{temp_sal_lags['rmse'] - temp_lags['rmse']:+.4f}"
    )
    print()
    print("Matched incremental test relative to persistence:")
    print(
        f"- Add temp now to persistence RMSE change: "
        f"{matched_temp['rmse'] - matched_persist['rmse']:+.4f}"
    )
    print(
        f"- Add temp+salinity now to persistence RMSE change: "
        f"{matched_temp_sal['rmse'] - matched_persist['rmse']:+.4f}"
    )
    print(
        f"- Add temp lags to persistence RMSE change: "
        f"{matched_temp_lags['rmse'] - matched_persist['rmse']:+.4f}"
    )
    print(
        f"- Add temp+salinity lags to persistence RMSE change: "
        f"{matched_temp_sal_lags['rmse'] - matched_persist['rmse']:+.4f}"
    )
    print()
    print("Matched incremental salinity test:")
    print(
        f"- Same-window RMSE change (persistence+temp+salinity minus persistence+temp): "
        f"{matched_temp_sal['rmse'] - matched_temp['rmse']:+.4f}"
    )
    print(
        f"- Same-window RMSE change (persistence+temp+salinity lags minus persistence+temp lags): "
        f"{matched_temp_sal_lags['rmse'] - matched_temp_lags['rmse']:+.4f}"
    )
    print()

    print("Model coefficients:")
    for result in results:
        print(f"[{result['model']}]")
        for name, value in result["coefficients"].items():
            print(f"  {name}: {value:+.5f}")
    print()
    print("Matched model coefficients:")
    for result in matched_results:
        print(f"[{result['model']}]")
        for name, value in result["coefficients"].items():
            print(f"  {name}: {value:+.5f}")


if __name__ == "__main__":
    main()
