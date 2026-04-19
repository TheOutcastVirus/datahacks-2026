from __future__ import annotations

import argparse
import json
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


DEFAULT_MODEL_PATH = Path("data/annual/sojs_portland_annual_model.json")
DEFAULT_TRAINING_PATH = Path("data/annual/sojs_portland_annual_training.csv")
DEFAULT_OUTPUT_DIR = Path("data/projections")
DEFAULT_PLOT_DIR = Path("plots/projections")
DEFAULT_HORIZON_YEARS = 100
DEFAULT_INTERVAL_Z = 1.2815515655446004
DEFAULT_N_SIMULATIONS = 4000
SUMMARY_ORDER = ["low", "baseline", "high"]
SUMMARY_QUANTILES = {"low": 0.25, "baseline": 0.5, "high": 0.75}
SUMMARY_COLORS = {
    "low": "#54a24b",
    "baseline": "#1f77b4",
    "high": "#e45756",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project annual Portland sea level for the next century using the "
            "historical annual trend plus the fitted annual-model noise structure."
        )
    )
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--training-path", type=Path, default=DEFAULT_TRAINING_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--horizon-years", type=int, default=DEFAULT_HORIZON_YEARS)
    parser.add_argument("--n-simulations", type=int, default=DEFAULT_N_SIMULATIONS)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if not args.model_path.exists():
        raise SystemExit(f"Annual model JSON not found: {args.model_path}")
    if not args.training_path.exists():
        raise SystemExit(f"Annual training table not found: {args.training_path}")
    if args.horizon_years < 1:
        raise SystemExit("--horizon-years must be at least 1.")
    if args.n_simulations < 100:
        raise SystemExit("--n-simulations must be at least 100.")


def load_model(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_training_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["year"] = frame["year"].astype(int)
    return frame.sort_values("year", kind="stable").reset_index(drop=True)


def land_motion_adjustment(model: dict[str, object], years: np.ndarray) -> np.ndarray:
    raw = -(
        float(model["relative_land_motion_mm_yr"]) / 1000.0
    ) * (years.astype(float) - float(model["land_motion_reference_year"]))
    return raw - float(model["land_motion_reference_mean_m"])


def estimate_noise_model(model: dict[str, object]) -> tuple[np.ndarray, float]:
    residuals = np.asarray(model["training_residuals_m"], dtype=float)
    centered = residuals - float(residuals.mean())
    if len(centered) < 2 or np.allclose(centered.std(ddof=0), 0.0):
        return centered, 0.0

    numerator = float(np.dot(centered[1:], centered[:-1]))
    denominator = float(np.dot(centered[:-1], centered[:-1]))
    phi = numerator / denominator if denominator > 0.0 else 0.0
    phi = float(np.clip(phi, -0.95, 0.95))
    innovations = centered[1:] - phi * centered[:-1]
    if innovations.size == 0 or np.allclose(innovations.std(ddof=0), 0.0):
        innovations = centered
        phi = 0.0
    return innovations, phi


def simulate_noise_paths(
    model: dict[str, object],
    *,
    n_years: int,
    n_simulations: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    residuals = np.asarray(model["training_residuals_m"], dtype=float)
    centered_residuals = residuals - float(residuals.mean())
    innovations, phi = estimate_noise_model(model)
    rng = np.random.default_rng(20260419)

    if centered_residuals.size == 0:
        noise_paths = np.zeros((n_simulations, n_years), dtype=float)
        return noise_paths, centered_residuals, phi

    noise_paths = np.empty((n_simulations, n_years), dtype=float)
    initial_state = rng.choice(centered_residuals, size=n_simulations, replace=True)
    noise_paths[:, 0] = phi * initial_state + rng.choice(innovations, size=n_simulations, replace=True)
    for index in range(1, n_years):
        shocks = rng.choice(innovations, size=n_simulations, replace=True)
        noise_paths[:, index] = phi * noise_paths[:, index - 1] + shocks
    return noise_paths, centered_residuals, phi


def simulate_trend_paths(
    model: dict[str, object],
    years: np.ndarray,
    *,
    n_simulations: int,
) -> np.ndarray:
    bootstrap_coefficients = np.asarray(model["bootstrap_coefficients"], dtype=float)
    rng = np.random.default_rng(20260419)
    sample_index = rng.choice(len(bootstrap_coefficients), size=n_simulations, replace=True)
    sampled_coefficients = bootstrap_coefficients[sample_index]
    trend_time = years.astype(float) - float(model["origin_year"])

    slope_samples = sampled_coefficients[:, 1]
    intercept_samples = sampled_coefficients[:, 0]
    trend_component = (
        intercept_samples[:, None] + slope_samples[:, None] * trend_time[None, :]
    )

    observed_trend = (
        float(model["observed_target_trend_intercept_m"])
        + float(model["observed_target_trend_slope_m_per_year"]) * trend_time
    )
    trend_component += (observed_trend - trend_component.mean(axis=0))[None, :]
    return trend_component


def build_summary_rows(
    years: np.ndarray,
    absolute_paths: np.ndarray,
) -> pd.DataFrame:
    mean_projection = absolute_paths.mean(axis=0)
    median_projection = np.quantile(absolute_paths, SUMMARY_QUANTILES["baseline"], axis=0)
    lower_projection = np.quantile(absolute_paths, SUMMARY_QUANTILES["low"], axis=0)
    upper_projection = np.quantile(absolute_paths, SUMMARY_QUANTILES["high"], axis=0)
    lower_80 = np.quantile(absolute_paths, 0.1, axis=0)
    upper_80 = np.quantile(absolute_paths, 0.9, axis=0)
    sigma = absolute_paths.std(axis=0, ddof=0)

    scenario_values = {
        "low": lower_projection,
        "baseline": mean_projection,
        "high": upper_projection,
    }
    rows: list[dict[str, float | int | str]] = []
    for scenario in SUMMARY_ORDER:
        for index, year in enumerate(years):
            rows.append(
                {
                    "scenario": scenario,
                    "year": int(year),
                    "predicted_m": float(scenario_values[scenario][index]),
                    "predicted_median_m": float(median_projection[index]),
                    "predicted_lower_80_m": float(lower_80[index]),
                    "predicted_upper_80_m": float(upper_80[index]),
                    "total_sigma_m": float(sigma[index]),
                }
            )
    return pd.DataFrame(rows)


def build_projection_frame(
    model: dict[str, object],
    training: pd.DataFrame,
    *,
    horizon_years: int,
    n_simulations: int,
) -> tuple[pd.DataFrame, dict[str, float]]:
    last_year = int(training["year"].dropna().max())
    years = np.arange(last_year + 1, last_year + horizon_years + 1, dtype=int)
    trend_paths = simulate_trend_paths(model, years, n_simulations=n_simulations)
    noise_paths, centered_residuals, phi = simulate_noise_paths(
        model,
        n_years=len(years),
        n_simulations=n_simulations,
    )

    adjusted_paths = trend_paths + noise_paths
    land_motion = land_motion_adjustment(model, years)
    absolute_paths = adjusted_paths + land_motion[None, :] + float(model["target_baseline_m"])
    summary = build_summary_rows(years, absolute_paths)
    diagnostics = {
        "n_simulations": int(absolute_paths.shape[0]),
        "noise_ar1_phi": float(phi),
        "training_noise_sigma_m": float(centered_residuals.std(ddof=1)) if centered_residuals.size > 1 else 0.0,
    }
    return summary, diagnostics


def save_projection_dataset(
    projections: pd.DataFrame,
    diagnostics: dict[str, float],
    output_path: Path,
) -> None:
    ds = (
        projections.set_index(["scenario", "year"])
        .to_xarray()
        .transpose("scenario", "year", ...)
    )
    ds.attrs.update(
        {
            "title": "Sojs Portland annual projections",
            "description": (
                "Century-scale annual Portland projections from an extracted historical "
                "trend coupled to the fitted annual-model noise structure."
            ),
            "projection_method": "historical_trend_plus_model_noise",
            "noise_ar1_phi": diagnostics["noise_ar1_phi"],
            "n_simulations": diagnostics["n_simulations"],
            "training_noise_sigma_m": diagnostics["training_noise_sigma_m"],
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoding: dict[str, dict[str, object]] = {}
    for name, data_array in ds.data_vars.items():
        if np.issubdtype(data_array.dtype, np.floating):
            encoding[name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
    ds.to_netcdf(output_path, encoding=encoding)
    ds.close()


def save_projection_plot(
    training: pd.DataFrame,
    projections: pd.DataFrame,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    observed = training.dropna(subset=["portland_msl_m"])
    ax.plot(
        observed["year"],
        observed["portland_msl_m"],
        color="black",
        linewidth=1.5,
        label="Observed Portland annual mean",
    )

    baseline = projections[projections["scenario"] == "baseline"].sort_values("year", kind="stable")
    low = projections[projections["scenario"] == "low"].sort_values("year", kind="stable")
    high = projections[projections["scenario"] == "high"].sort_values("year", kind="stable")

    ax.fill_between(
        baseline["year"].to_numpy(dtype=int),
        baseline["predicted_lower_80_m"].to_numpy(dtype=float),
        baseline["predicted_upper_80_m"].to_numpy(dtype=float),
        color="#1f77b4",
        alpha=0.18,
        label="80% simulation interval",
    )
    for scenario, group in [("low", low), ("baseline", baseline), ("high", high)]:
        ax.plot(
            group["year"].to_numpy(dtype=int),
            group["predicted_m"].to_numpy(dtype=float),
            color=SUMMARY_COLORS[scenario],
            linewidth=1.8,
            label=f"{scenario} summary path",
        )

    ax.set_title("Sojs Portland annual projection: extracted trend plus trained noise")
    ax.set_xlabel("Year")
    ax.set_ylabel("Sea level (m)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def save_summary_markdown(
    model: dict[str, object],
    projections: pd.DataFrame,
    diagnostics: dict[str, float],
    output_path: Path,
) -> None:
    lines = [
        "# Sojs Annual Projection Summary",
        "",
        f"**Projection model noise source:** `{model['model_name']}`",
        f"**Projection years:** {int(projections['year'].min())} to {int(projections['year'].max())}",
        f"**Projection method:** extracted historical trend plus trained noise simulation (`{int(diagnostics['n_simulations'])}` paths).",
        "**Summary paths:** low = 25th percentile, baseline = simulation mean, high = 75th percentile.",
        "",
        "## End-of-horizon readout",
        "",
        "| Summary path | Final year | Projected sea level (m) | 80% lower (m) | 80% upper (m) |",
        "|--------------|-----------:|------------------------:|--------------:|--------------:|",
    ]
    for scenario in SUMMARY_ORDER:
        row = projections[projections["scenario"] == scenario].sort_values("year").iloc[-1]
        lines.append(
            f"| {scenario} | {int(row['year'])} | {row['predicted_m']:.4f} | "
            f"{row['predicted_lower_80_m']:.4f} | {row['predicted_upper_80_m']:.4f} |"
        )
    lines += [
        "",
        "## Notes",
        "",
        f"- Historical trend slope used in adjusted-target space: {float(model['observed_target_trend_slope_m_per_year']):.6f} m/year.",
        f"- Learned noise AR(1) coefficient: {diagnostics['noise_ar1_phi']:.3f}.",
        f"- Training noise sigma from model residuals: {diagnostics['training_noise_sigma_m']:.5f} m.",
        "- Land motion is added back deterministically after simulating the adjusted annual target path.",
        "- The projection is annual-average only and extends the next century from the retained historical trend rather than extrapolating exogenous driver scenarios.",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)

    model = load_model(args.model_path)
    training = load_training_frame(args.training_path)
    projections, diagnostics = build_projection_frame(
        model,
        training,
        horizon_years=args.horizon_years,
        n_simulations=args.n_simulations,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.plot_dir.mkdir(parents=True, exist_ok=True)
    projections.to_csv(
        args.output_dir / "sojs_portland_annual_projections.csv",
        index=False,
        float_format="%.6f",
    )
    save_projection_dataset(
        projections,
        diagnostics,
        args.output_dir / "sojs_portland_annual_projections.nc",
    )
    save_projection_plot(training, projections, args.plot_dir / "portland_annual_projection.png")
    save_summary_markdown(
        model,
        projections,
        diagnostics,
        args.plot_dir / "sojs_annual_projection_summary.md",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
