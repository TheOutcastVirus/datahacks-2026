"""Build a labeled NetCDF time series from a NOAA CO-OPS monthly CSV."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import xarray as xr

from project_paths import PROCESSED_COOPS_NC, RAW_COOPS_CSV


IN_CSV = RAW_COOPS_CSV
OUT_NC = PROCESSED_COOPS_NC

NUMERIC_COLUMNS = {
    "Highest": "highest",
    "MHHW (m)": "mhhw",
    "MHW (m)": "mhw",
    "MSL (m)": "msl",
    "MTL (m)": "mtl",
    "MLW (m)": "mlw",
    "MLLW (m)": "mllw",
    "Lowest (m)": "lowest",
    "Inf": "inf_code",
}

VARIABLE_ATTRS = {
    "highest": {
        "long_name": "Monthly highest water level",
        "units": "m",
        "feature_role": "diagnostic",
    },
    "mhhw": {
        "long_name": "Mean higher high water",
        "units": "m",
        "feature_role": "diagnostic",
    },
    "mhw": {
        "long_name": "Mean high water",
        "units": "m",
        "feature_role": "diagnostic",
    },
    "msl": {
        "long_name": "Mean sea level",
        "units": "m",
        "feature_role": "target_raw",
    },
    "mtl": {
        "long_name": "Mean tide level",
        "units": "m",
        "feature_role": "diagnostic",
    },
    "mlw": {
        "long_name": "Mean low water",
        "units": "m",
        "feature_role": "diagnostic",
    },
    "mllw": {
        "long_name": "Mean lower low water",
        "units": "m",
        "feature_role": "diagnostic",
    },
    "lowest": {
        "long_name": "Monthly lowest water level",
        "units": "m",
        "feature_role": "diagnostic",
    },
    "sea_level_anomaly": {
        "long_name": "Monthly mean sea level anomaly relative to monthly climatology",
        "units": "m",
        "feature_role": "target",
    },
    "msl_monthly_climatology": {
        "long_name": "Monthly climatology of mean sea level",
        "units": "m",
        "feature_role": "reference",
    },
    "year": {
        "long_name": "Calendar year",
        "feature_role": "calendar_feature",
    },
    "month_number": {
        "long_name": "Calendar month number",
        "feature_role": "calendar_feature",
    },
    "time_index_months": {
        "long_name": "Months since start of record",
        "feature_role": "trend_feature",
    },
    "month_sin": {
        "long_name": "Sine transform of calendar month",
        "feature_role": "seasonal_feature",
    },
    "month_cos": {
        "long_name": "Cosine transform of calendar month",
        "feature_role": "seasonal_feature",
    },
    "is_missing_month": {
        "long_name": "Indicator that the month was absent from the source CSV",
        "flag_values": "0 1",
        "feature_role": "quality_flag",
    },
    "inf_code": {
        "long_name": "NOAA CO-OPS source infill/flag code",
        "feature_role": "quality_flag",
    },
    "is_flagged_or_infilled": {
        "long_name": "Indicator that the source infill/flag code was non-zero",
        "flag_values": "0 1",
        "feature_role": "quality_flag",
    },
}


def load_source(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(
        df["Date"] + " " + df["Time (GMT)"],
        format="%Y/%m/%d %H:%M",
        errors="raise",
    )
    df = df.rename(columns=NUMERIC_COLUMNS)

    for column in NUMERIC_COLUMNS.values():
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.drop(columns=["Date", "Time (GMT)"]).sort_values("time")
    if df["time"].duplicated().any():
        raise ValueError("Source CSV contains duplicate timestamps.")

    return df


def build_dataset(df: pd.DataFrame) -> xr.Dataset:
    full_time = pd.date_range(df["time"].min(), df["time"].max(), freq="MS")
    monthly = df.set_index("time").reindex(full_time)
    monthly.index.name = "time"

    monthly["is_missing_month"] = monthly["msl"].isna().astype(np.int8)
    monthly["year"] = monthly.index.year.astype(np.int16)
    monthly["month_number"] = monthly.index.month.astype(np.int8)
    monthly["time_index_months"] = np.arange(len(monthly), dtype=np.int32)

    angle = 2.0 * np.pi * (monthly["month_number"] - 1) / 12.0
    monthly["month_sin"] = np.sin(angle).astype(np.float32)
    monthly["month_cos"] = np.cos(angle).astype(np.float32)

    climatology = monthly.groupby("month_number")["msl"].mean()
    monthly["sea_level_anomaly"] = (
        monthly["msl"] - monthly["month_number"].map(climatology)
    )
    monthly["is_flagged_or_infilled"] = (
        monthly["inf_code"].fillna(0).ne(0).astype(np.int8)
    )

    time_values = monthly.index.to_numpy()
    month_values = np.arange(1, 13, dtype=np.int8)

    ds = xr.Dataset(
        coords={
            "time": ("time", time_values, {"long_name": "Monthly timestamp"}),
            "month": (
                "month",
                month_values,
                {"long_name": "Calendar month number"},
            ),
        },
        attrs={
            "title": "La Jolla NOAA CO-OPS monthly sea level features",
            "station_id": "9410230",
            "station_name": "La Jolla",
            "time_zone": "GMT",
            "source": "NOAA CO-OPS monthly water level CSV",
            "source_file": path.name if (path := IN_CSV) else "",
            "target_variable": "sea_level_anomaly",
            "target_description": (
                "MSL anomaly relative to the station's monthly climatology"
            ),
        },
    )

    float32_vars = [
        "highest",
        "mhhw",
        "mhw",
        "msl",
        "mtl",
        "mlw",
        "mllw",
        "lowest",
        "sea_level_anomaly",
        "month_sin",
        "month_cos",
    ]
    int_vars = [
        "year",
        "month_number",
        "time_index_months",
        "is_missing_month",
        "is_flagged_or_infilled",
    ]

    for name in float32_vars:
        ds[name] = ("time", monthly[name].to_numpy(dtype=np.float32), VARIABLE_ATTRS[name])

    ds["inf_code"] = (
        "time",
        monthly["inf_code"].fillna(-1).to_numpy(dtype=np.int16),
        VARIABLE_ATTRS["inf_code"] | {"missing_value_code": -1},
    )

    for name in int_vars:
        ds[name] = ("time", monthly[name].to_numpy(), VARIABLE_ATTRS[name])

    ds["msl_monthly_climatology"] = (
        "month",
        climatology.reindex(month_values).to_numpy(dtype=np.float32),
        VARIABLE_ATTRS["msl_monthly_climatology"],
    )

    return ds


def write_dataset(ds: xr.Dataset, out_nc: Path) -> None:
    tmp_nc = out_nc.with_suffix(".tmp.nc")
    if tmp_nc.exists():
        tmp_nc.unlink()

    encoding = {
        name: {"zlib": True, "complevel": 4}
        for name in ds.data_vars
        if name not in {"year", "month_number", "time_index_months", "is_missing_month", "is_flagged_or_infilled", "inf_code"}
    }

    try:
        ds.to_netcdf(tmp_nc, encoding=encoding)
        os.replace(tmp_nc, out_nc)
    except PermissionError as exc:
        if tmp_nc.exists():
            tmp_nc.unlink()
        raise PermissionError(
            f"Could not write {out_nc}. Close any notebook or viewer holding the file open."
        ) from exc
    finally:
        ds.close()


def main() -> None:
    df = load_source(IN_CSV)
    ds = build_dataset(df)
    write_dataset(ds, OUT_NC)
    print(f"Wrote {OUT_NC}")
    print(f"time range: {df['time'].min()} -> {df['time'].max()}")
    print(f"rows in source CSV: {len(df)}")


if __name__ == "__main__":
    main()
