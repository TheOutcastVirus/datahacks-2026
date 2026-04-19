from __future__ import annotations

import argparse
from datetime import UTC, datetime
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


DEFAULT_MONTHLY_PATH = Path("data/normalized/sojs_active_monthly_normalized.nc")
DEFAULT_NAO_PATH = Path("data/nao/nao_monthly.nc")
DEFAULT_LAND_MOTION_PATH = Path("data/land_motion/portland_land_motion.nc")
DEFAULT_OUTPUT_DIR = Path("data/annual")
DEFAULT_PLOT_DIR = Path("plots/annual")
DEFAULT_MIN_MONTHS = 9
PORTLAND_VARIABLE = "portland_msl_m"
PREDICTOR_COLUMNS = [
    "copernicus_sla_gom_m",
    "greenland_mass_gt",
]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the Sojs annual Portland training table from the normalized monthly "
            "stack, NAO monthly data, and deterministic land-motion metadata."
        )
    )
    parser.add_argument("--monthly-path", type=Path, default=DEFAULT_MONTHLY_PATH)
    parser.add_argument("--nao-path", type=Path, default=DEFAULT_NAO_PATH)
    parser.add_argument("--land-motion-path", type=Path, default=DEFAULT_LAND_MOTION_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--min-months", type=int, default=DEFAULT_MIN_MONTHS)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if not args.monthly_path.exists():
        raise SystemExit(f"Monthly normalized dataset not found: {args.monthly_path}")
    if not args.nao_path.exists():
        raise SystemExit(f"NAO dataset not found: {args.nao_path}")
    if not args.land_motion_path.exists():
        raise SystemExit(f"Land-motion dataset not found: {args.land_motion_path}")
    if args.min_months < 1 or args.min_months > 12:
        raise SystemExit("--min-months must be between 1 and 12.")


def load_monthly_frame(path: Path) -> pd.DataFrame:
    ds = xr.open_dataset(path)
    try:
        frame = ds.to_dataframe().reset_index()
    finally:
        ds.close()
    frame["time"] = pd.to_datetime(frame["time"])
    frame["year"] = frame["time"].dt.year.astype(int)
    return frame.sort_values("time").reset_index(drop=True)


def load_nao_frame(path: Path) -> pd.DataFrame:
    ds = xr.open_dataset(path)
    try:
        frame = ds.to_dataframe().reset_index()
    finally:
        ds.close()
    frame["time"] = pd.to_datetime(frame["time"])
    frame["year"] = frame["time"].dt.year.astype(int)
    frame["month"] = frame["month"].astype(int)
    return frame.sort_values("time").reset_index(drop=True)


def load_land_motion_metadata(path: Path) -> dict[str, object]:
    ds = xr.open_dataset(path)
    try:
        frame = ds.to_dataframe().reset_index()
    finally:
        ds.close()
    if frame.empty:
        raise SystemExit(f"Land-motion dataset is empty: {path}")
    row = frame.iloc[0]
    return {
        "gia_metadata_mm_yr": float(row["gia_metadata_mm_yr"]),
        "gia_sigma_mm_yr": float(row["gia_sigma_mm_yr"]),
        "vlm_mm_yr": float(row["vlm_mm_yr"]),
        "vlm_sigma_mm_yr": float(row["vlm_sigma_mm_yr"]),
        "relative_land_motion_mm_yr": float(row["relative_land_motion_mm_yr"]),
        "relative_land_motion_sigma_mm_yr": float(row["relative_land_motion_sigma_mm_yr"]),
        "land_motion_kind": str(row["land_motion_kind"]),
        "land_motion_source": str(row["land_motion_source"]),
    }


def annual_mean_with_coverage(
    frame: pd.DataFrame,
    column: str,
    *,
    min_months: int,
) -> pd.DataFrame:
    grouped = frame.groupby("year", sort=True)[column]
    summary = grouped.agg(
        months_present=lambda s: int(s.notna().sum()),
        annual_mean=lambda s: float(s.dropna().mean()) if s.notna().sum() >= min_months else np.nan,
    )
    summary = summary.rename(
        columns={
            "months_present": f"months_present_{column}",
            "annual_mean": column,
        }
    )
    return summary


def build_portland_frame(monthly: pd.DataFrame, *, min_months: int) -> pd.DataFrame:
    years = pd.Index(sorted(monthly["year"].unique()), name="year")
    annual = pd.DataFrame(index=years)

    for column in [PORTLAND_VARIABLE, *PREDICTOR_COLUMNS]:
        annual = annual.join(annual_mean_with_coverage(monthly, column, min_months=min_months))

    valid_portland = annual[PORTLAND_VARIABLE].dropna()
    annual_mean = float(valid_portland.mean()) if not valid_portland.empty else np.nan
    annual["portland_msl_m_anomaly"] = annual[PORTLAND_VARIABLE] - annual_mean

    return annual.reset_index()


def build_nao_annual_frame(nao: pd.DataFrame, *, min_months: int) -> pd.DataFrame:
    years = pd.Index(sorted(nao["year"].unique()), name="year")
    annual = pd.DataFrame(index=years)

    annual_mean = nao.groupby("year", sort=True)["nao"].agg(
        months_present_nao_annual_mean=lambda s: int(s.notna().sum()),
        nao_annual_mean=lambda s: float(s.dropna().mean()) if s.notna().sum() >= min_months else np.nan,
    )
    annual = annual.join(annual_mean)

    winter = nao[nao["month"].isin([12, 1, 2])].copy()
    winter["winter_year"] = winter["year"] + (winter["month"] == 12).astype(int)
    djf = winter.groupby("winter_year", sort=True)["nao"].agg(
        months_present_nao_winter_djf=lambda s: int(s.notna().sum()),
        nao_winter_djf=lambda s: float(s.dropna().mean()) if s.notna().sum() >= 2 else np.nan,
    )
    djf.index.name = "year"
    annual = annual.join(djf, how="outer")

    annual["nao_annual_mean_prev_year"] = annual["nao_annual_mean"].shift(1)
    annual["nao_winter_djf_prev_year"] = annual["nao_winter_djf"].shift(1)
    annual["months_present_nao_annual_mean_prev_year"] = annual[
        "months_present_nao_annual_mean"
    ].shift(1)
    annual["months_present_nao_winter_djf_prev_year"] = annual[
        "months_present_nao_winter_djf"
    ].shift(1)
    return annual.reset_index()


def attach_land_motion_metadata(
    annual: pd.DataFrame,
    metadata: dict[str, object],
) -> pd.DataFrame:
    output = annual.copy()
    for key in [
        "gia_metadata_mm_yr",
        "gia_sigma_mm_yr",
        "vlm_mm_yr",
        "vlm_sigma_mm_yr",
        "relative_land_motion_mm_yr",
        "relative_land_motion_sigma_mm_yr",
        "land_motion_kind",
        "land_motion_source",
    ]:
        output[key] = metadata[key]

    target_years = output.loc[output[PORTLAND_VARIABLE].notna(), "year"]
    if target_years.empty:
        output["land_motion_adjustment_m"] = np.nan
        output["portland_target_adjusted_m"] = np.nan
        return output

    origin_year = int(target_years.min())
    raw = -(
        output["relative_land_motion_mm_yr"].astype(float) / 1000.0
    ) * (output["year"].astype(float) - float(origin_year))
    reference_mean = float(raw.loc[output[PORTLAND_VARIABLE].notna()].mean())
    output["land_motion_adjustment_m"] = raw - reference_mean
    output["portland_target_adjusted_m"] = (
        output["portland_msl_m_anomaly"] - output["land_motion_adjustment_m"]
    )
    return output


def build_dataset(frame: pd.DataFrame) -> xr.Dataset:
    indexed = frame.set_index("year")
    ds = xr.Dataset(coords={"year": indexed.index.to_numpy(dtype=np.int32)})

    object_columns = [column for column in indexed.columns if indexed[column].dtype == object]
    for column in indexed.columns:
        values = indexed[column]
        if column in object_columns:
            ds[column] = ("year", values.astype(str).to_numpy(dtype=object))
        else:
            ds[column] = ("year", values.to_numpy(dtype=float))

    ds.attrs.update(
        {
            "title": "Sojs Portland annual training dataset",
            "description": (
                "Calendar-year annual means for Portland relative sea level and retained "
                "annual predictors. A minimum monthly coverage threshold is enforced per "
                "series before a yearly mean is accepted."
            ),
            "history": (
                "Created by annual_projection_data.py on "
                f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            ),
            "minimum_months_per_year": DEFAULT_MIN_MONTHS,
            "excluded_required_annual_predictors": (
                "Argo and historical GRACE are intentionally excluded from the required "
                "annual projection table."
            ),
        }
    )
    return ds


def save_dataset(ds: xr.Dataset, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding: dict[str, dict[str, object]] = {}
    for name, data_array in ds.data_vars.items():
        if np.issubdtype(data_array.dtype, np.floating):
            encoding[name] = {"zlib": True, "complevel": 4, "_FillValue": np.nan}
    ds.to_netcdf(path, encoding=encoding)
    return path


def save_coverage_plot(frame: pd.DataFrame, path: Path) -> Path:
    columns = [
        "portland_msl_m",
        "copernicus_sla_gom_m",
        "greenland_mass_gt",
        "nao_annual_mean",
        "nao_winter_djf",
        "nao_annual_mean_prev_year",
        "nao_winter_djf_prev_year",
        "portland_target_adjusted_m",
    ]
    coverage = frame.set_index("year")[columns].notna().astype(int).T
    fig, ax = plt.subplots(figsize=(15, 5))
    image = ax.imshow(coverage.values, aspect="auto", interpolation="nearest", cmap="Greys")
    ax.set_title("Sojs Portland annual predictor coverage")
    ax.set_xlabel("Year")
    ax.set_ylabel("Variable")
    ax.set_yticks(np.arange(len(coverage.index)))
    ax.set_yticklabels(coverage.index)
    tick_positions = np.linspace(
        0,
        max(len(coverage.columns) - 1, 0),
        num=min(12, len(coverage.columns)),
        dtype=int,
    )
    if len(tick_positions) > 0:
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(coverage.columns.to_numpy()[tick_positions].astype(str), rotation=45, ha="right")
    fig.colorbar(image, ax=ax, label="Coverage (1 = present)")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)

    monthly = load_monthly_frame(args.monthly_path)
    nao = load_nao_frame(args.nao_path)
    land_motion = load_land_motion_metadata(args.land_motion_path)

    annual = build_portland_frame(monthly, min_months=args.min_months)
    annual = annual.merge(
        build_nao_annual_frame(nao, min_months=args.min_months),
        on="year",
        how="left",
        sort=True,
    )
    annual = attach_land_motion_metadata(annual, land_motion)
    annual = annual.sort_values("year", kind="stable").reset_index(drop=True)

    dataset = build_dataset(annual)
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        args.plot_dir.mkdir(parents=True, exist_ok=True)
        annual.to_csv(
            args.output_dir / "sojs_portland_annual_training.csv",
            index=False,
            float_format="%.6f",
        )
        save_dataset(dataset, args.output_dir / "sojs_portland_annual_training.nc")
        save_coverage_plot(annual, args.plot_dir / "portland_annual_coverage.png")
    finally:
        dataset.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
