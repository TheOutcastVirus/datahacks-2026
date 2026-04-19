from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import xarray as xr


DEFAULT_OUTPUT_DIR = Path("data/land_motion")
DEFAULT_PLOT_DIR = Path("plots/land_motion")
DEFAULT_STATION_NAME = "Portland"
DEFAULT_STATION_ID = "8418150"
DEFAULT_GIA_MM_YR = 1.1
DEFAULT_GIA_SIGMA_MM_YR = 0.2
DEFAULT_VLM_MM_YR = 0.0
DEFAULT_VLM_SIGMA_MM_YR = 0.8
DEFAULT_SOURCE = "Sojs first-pass Portland land-motion metadata"
DEFAULT_KIND = "combined_relative_land_motion"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Write a narrow Portland land-motion metadata artifact for the Sojs "
            "annual projection workflow."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--plot-dir", type=Path, default=DEFAULT_PLOT_DIR)
    parser.add_argument("--station-name", default=DEFAULT_STATION_NAME)
    parser.add_argument("--station-id", default=DEFAULT_STATION_ID)
    parser.add_argument("--gia-mm-yr", type=float, default=DEFAULT_GIA_MM_YR)
    parser.add_argument("--gia-sigma-mm-yr", type=float, default=DEFAULT_GIA_SIGMA_MM_YR)
    parser.add_argument("--vlm-mm-yr", type=float, default=DEFAULT_VLM_MM_YR)
    parser.add_argument("--vlm-sigma-mm-yr", type=float, default=DEFAULT_VLM_SIGMA_MM_YR)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--kind", default=DEFAULT_KIND)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.gia_sigma_mm_yr < 0.0:
        raise SystemExit("--gia-sigma-mm-yr must be zero or greater.")
    if args.vlm_sigma_mm_yr < 0.0:
        raise SystemExit("--vlm-sigma-mm-yr must be zero or greater.")


def build_summary_frame(args: argparse.Namespace) -> pd.DataFrame:
    relative_rate = float(args.gia_mm_yr + args.vlm_mm_yr)
    relative_sigma = float(np.hypot(args.gia_sigma_mm_yr, args.vlm_sigma_mm_yr))
    return pd.DataFrame(
        [
            {
                "station_name": args.station_name,
                "station_id": args.station_id,
                "land_motion_kind": args.kind,
                "land_motion_source": args.source,
                "gia_metadata_mm_yr": float(args.gia_mm_yr),
                "gia_sigma_mm_yr": float(args.gia_sigma_mm_yr),
                "vlm_mm_yr": float(args.vlm_mm_yr),
                "vlm_sigma_mm_yr": float(args.vlm_sigma_mm_yr),
                "relative_land_motion_mm_yr": relative_rate,
                "relative_land_motion_sigma_mm_yr": relative_sigma,
                "notes": (
                    "Deterministic first-pass site metadata for annual target adjustment. "
                    "VLM is retained explicitly with uncertainty rather than hidden inside GIA."
                ),
            }
        ]
    )


def build_dataset(summary: pd.DataFrame) -> xr.Dataset:
    indexed = summary.set_index("station_name")
    ds = xr.Dataset(coords={"station_name": indexed.index.to_numpy(dtype=object)})

    string_columns = ["station_id", "land_motion_kind", "land_motion_source", "notes"]
    numeric_columns = [
        "gia_metadata_mm_yr",
        "gia_sigma_mm_yr",
        "vlm_mm_yr",
        "vlm_sigma_mm_yr",
        "relative_land_motion_mm_yr",
        "relative_land_motion_sigma_mm_yr",
    ]
    for column in string_columns:
        ds[column] = ("station_name", indexed[column].astype(str).to_numpy(dtype=object))
    for column in numeric_columns:
        ds[column] = ("station_name", indexed[column].to_numpy(dtype=float))

    ds.attrs.update(
        {
            "title": "Sojs Portland land-motion metadata",
            "description": (
                "Single-site deterministic land-motion metadata for the annual Sojs "
                "projection track."
            ),
            "history": (
                "Created by land_motion.py on "
                f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_args(args)

    summary = build_summary_frame(args)
    dataset = build_dataset(summary)
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        args.plot_dir.mkdir(parents=True, exist_ok=True)
        save_dataset(dataset, args.output_dir / "portland_land_motion.nc")
        summary.to_csv(args.plot_dir / "portland_land_motion_summary.csv", index=False)
    finally:
        dataset.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
