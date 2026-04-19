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
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "matplotlib is not installed. Run `pip install -r requirements.txt` first."
    ) from exc


DEFAULT_INPUT = Path("data/normalized/sojs_active_modern_overlap.nc")
DEFAULT_OUTPUT_DIR = Path("data/budget")
DEFAULT_PLOT_DIR = Path("plots/budget")

STATIONS = {
    "Portland": {
        "variable": "portland_msl_m",
        "gia_rate_mm_yr": 1.1,
    },
    "Bar Harbor": {
        "variable": "bar_harbor_msl_m",
        "gia_rate_mm_yr": 1.3,
    },
    "Rockland": {
        "variable": "rockland_msl_m",
        "gia_rate_mm_yr": 1.2,
    },
}

PREDICTOR_SPECS = [
    ("copernicus_sla_gom_m_zscore", "copernicus_sla_component_m"),
    ("grace_hist_lwe_thickness_gom_m_zscore", "grace_hist_mass_component_m"),
    ("greenland_mass_gt_zscore", "greenland_mass_component_m"),
]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the first reduced Sojs observational budget from the normalized "
            "modern-overlap dataset and generate residual diagnostics."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    return parser.parse_args(argv)


def to_frame(ds: xr.Dataset) -> pd.DataFrame:
    frame = ds.to_dataframe().reset_index()
    frame["time"] = pd.to_datetime(frame["time"])
    frame = frame.set_index("time").sort_index()
    return frame


def years_since_start(index: pd.DatetimeIndex) -> np.ndarray:
    elapsed_days = np.asarray((index - index[0]).days, dtype=float)
    return elapsed_days / 365.2425


def fit_station_budget(
    frame: pd.DataFrame,
    *,
    station_name: str,
    station_variable: str,
    gia_rate_mm_yr: float,
) -> tuple[pd.DataFrame, dict[str, object]]:
    required_columns = [station_variable, f"{station_variable}_anomaly"]
    required_columns.extend(name for name, _ in PREDICTOR_SPECS)

    working = frame[required_columns].dropna().copy()
    if working.empty:
        raise ValueError(f"No overlap data available for {station_name}.")

    years = years_since_start(working.index)
    gia_term = -(gia_rate_mm_yr / 1000.0) * years
    gia_term = gia_term - gia_term.mean()

    y = working[f"{station_variable}_anomaly"].to_numpy(dtype=float)
    x_columns = [name for name, _ in PREDICTOR_SPECS]
    x = working[x_columns].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(working)), x])
    y_adjusted = y - gia_term
    coefficients, _, _, _ = np.linalg.lstsq(design, y_adjusted, rcond=None)

    intercept = coefficients[0]
    predictor_betas = coefficients[1:]
    component_values: dict[str, np.ndarray] = {}
    for beta, (predictor_name, component_name) in zip(predictor_betas, PREDICTOR_SPECS, strict=True):
        component_values[component_name] = beta * working[predictor_name].to_numpy(dtype=float)

    modeled_without_gia = intercept + np.sum(np.column_stack(list(component_values.values())), axis=1)
    predicted = modeled_without_gia + gia_term
    residual = y - predicted

    observed = working[station_variable].to_numpy(dtype=float)
    predicted_absolute = observed.mean() + predicted
    residual_trend_m_per_year = np.polyfit(years, residual, deg=1)[0] if len(working) > 1 else np.nan
    correlation = np.corrcoef(y, predicted)[0, 1] if len(working) > 1 else np.nan
    ss_total = np.sum((y - y.mean()) ** 2)
    ss_res = np.sum(residual**2)
    r_squared = 1.0 - ss_res / ss_total if ss_total > 0 else np.nan

    fitted = pd.DataFrame(index=working.index)
    fitted["station_name"] = station_name
    fitted["observed_m"] = observed
    fitted["observed_anomaly_m"] = y
    fitted["gia_component_m"] = gia_term
    fitted["predicted_anomaly_m"] = predicted
    fitted["predicted_m"] = predicted_absolute
    fitted["residual_m"] = residual
    for component_name, values in component_values.items():
        fitted[component_name] = values

    summary = {
        "station": station_name,
        "status": "modeled",
        "gia_rate_mm_yr": gia_rate_mm_yr,
        "time_start": working.index.min().strftime("%Y-%m-%d"),
        "time_end": working.index.max().strftime("%Y-%m-%d"),
        "time_steps": int(len(working)),
        "rmse_m": float(np.sqrt(np.mean(residual**2))),
        "mae_m": float(np.mean(np.abs(residual))),
        "bias_m": float(np.mean(residual)),
        "residual_std_m": float(np.std(residual, ddof=0)),
        "correlation": float(correlation),
        "r_squared": float(r_squared),
        "residual_trend_mm_yr": float(residual_trend_m_per_year * 1000.0),
        "intercept_m": float(intercept),
        "beta_copernicus_sla_m_per_std": float(predictor_betas[0]),
        "beta_grace_hist_mass_m_per_std": float(predictor_betas[1]),
        "beta_greenland_mass_m_per_std": float(predictor_betas[2]),
    }
    return fitted, summary


def station_unavailable_summary(
    frame: pd.DataFrame,
    *,
    station_name: str,
    station_variable: str,
    gia_rate_mm_yr: float,
) -> dict[str, object]:
    valid = frame[station_variable].dropna()
    return {
        "station": station_name,
        "status": "excluded_no_modern_overlap",
        "gia_rate_mm_yr": gia_rate_mm_yr,
        "time_start": valid.index.min().strftime("%Y-%m-%d") if not valid.empty else "",
        "time_end": valid.index.max().strftime("%Y-%m-%d") if not valid.empty else "",
        "time_steps": 0,
        "rmse_m": np.nan,
        "mae_m": np.nan,
        "bias_m": np.nan,
        "residual_std_m": np.nan,
        "correlation": np.nan,
        "r_squared": np.nan,
        "residual_trend_mm_yr": np.nan,
        "intercept_m": np.nan,
        "beta_copernicus_sla_m_per_std": np.nan,
        "beta_grace_hist_mass_m_per_std": np.nan,
        "beta_greenland_mass_m_per_std": np.nan,
    }


def save_budget_dataset(fitted_frames: list[pd.DataFrame], output_path: Path) -> Path:
    all_rows = pd.concat(fitted_frames).reset_index().rename(columns={"index": "time"})
    dataset = (
        all_rows.set_index(["time", "station_name"])
        .to_xarray()
        .transpose("station_name", "time", ...)
    )
    dataset.attrs.update(
        {
            "title": "Sojs reduced observational budget analysis",
            "description": (
                "Reduced observational budget fit for the active modern-overlap data stack."
            ),
            "predictors": ", ".join(name for name, _ in PREDICTOR_SPECS),
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoding: dict[str, dict[str, object]] = {}
    for variable_name in dataset.data_vars:
        encoding[variable_name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
    dataset.to_netcdf(output_path, encoding=encoding)
    dataset.close()
    return output_path


def save_station_plot(station_frame: pd.DataFrame, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(
        station_frame.index,
        station_frame["observed_anomaly_m"],
        label="Observed anomaly",
        linewidth=1.6,
        color="#4C78A8",
    )
    ax.plot(
        station_frame.index,
        station_frame["predicted_anomaly_m"],
        label="Reduced budget prediction",
        linewidth=1.6,
        color="#F58518",
    )
    ax.plot(
        station_frame.index,
        station_frame["residual_m"],
        label="Residual",
        linewidth=1.0,
        color="#54A24B",
        alpha=0.9,
    )
    ax.set_title(f"Reduced observational budget: {station_frame['station_name'].iloc[0]}")
    ax.set_xlabel("Time")
    ax.set_ylabel("Sea level anomaly (m)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def save_residual_plot(fitted_frames: list[pd.DataFrame], output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 5))
    for station_frame in fitted_frames:
        station_name = station_frame["station_name"].iloc[0]
        ax.plot(
            station_frame.index,
            station_frame["residual_m"],
            linewidth=1.3,
            label=station_name,
        )
    ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    ax.set_title("Reduced observational budget residuals")
    ax.set_xlabel("Time")
    ax.set_ylabel("Residual (m)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def save_summary_markdown(summary: pd.DataFrame, output_path: Path) -> Path:
    modeled = summary[summary["status"] == "modeled"].copy()
    lines = [
        "# Sojs Reduced Observational Budget Summary",
        "",
        "## Modeled stations",
        "",
    ]
    for _, row in modeled.iterrows():
        lines.extend(
            [
                f"### {row['station']}",
                "",
                f"- Window: {row['time_start']} to {row['time_end']} ({int(row['time_steps'])} months)",
                f"- RMSE: {row['rmse_m']:.4f} m",
                f"- Correlation: {row['correlation']:.3f}",
                f"- R-squared: {row['r_squared']:.3f}",
                f"- Residual trend: {row['residual_trend_mm_yr']:.3f} mm/yr",
                "",
            ]
        )

    rockland = summary[summary["station"] == "Rockland"].iloc[0]
    lines.extend(
        [
            "## Coverage constraint",
            "",
            (
                "Rockland is excluded from the reduced modern budget fit because its retained "
                "CO-OPS record ends in 1987 and has zero overlap with the 2002-2017 modern "
                "multi-source stack."
            ),
            "",
            "## Recommended next data families",
            "",
            "- Atmospheric and climate drivers to explain residual variance not captured by regional SLA and mass terms.",
            "- Ocean-interior or steric drivers if the reduced observational budget is not sufficient for hindcast skill.",
            "- A modern local Rockland-level target or proxy if Rockland remains the primary prediction site.",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    ds = xr.open_dataset(args.input)
    try:
        frame = to_frame(ds)
    finally:
        ds.close()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.plot_dir.mkdir(parents=True, exist_ok=True)

    fitted_frames: list[pd.DataFrame] = []
    summaries: list[dict[str, object]] = []

    for station_name, config in STATIONS.items():
        station_variable = config["variable"]
        gia_rate_mm_yr = float(config["gia_rate_mm_yr"])
        if station_name == "Rockland":
            summaries.append(
                station_unavailable_summary(
                    frame,
                    station_name=station_name,
                    station_variable=station_variable,
                    gia_rate_mm_yr=gia_rate_mm_yr,
                )
            )
            continue

        fitted, summary = fit_station_budget(
            frame,
            station_name=station_name,
            station_variable=station_variable,
            gia_rate_mm_yr=gia_rate_mm_yr,
        )
        fitted_frames.append(fitted)
        summaries.append(summary)
        save_station_plot(
            fitted,
            args.plot_dir / f"{station_name.lower().replace(' ', '_')}_reduced_budget.png",
        )

    if not fitted_frames:
        raise SystemExit("No station budget fits were generated.")

    save_budget_dataset(fitted_frames, args.output_dir / "sojs_reduced_budget.nc")
    save_residual_plot(fitted_frames, args.plot_dir / "sojs_reduced_budget_residuals.png")

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(args.plot_dir / "sojs_reduced_budget_summary.csv", index=False)
    save_summary_markdown(summary_df, args.plot_dir / "sojs_reduced_budget_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
