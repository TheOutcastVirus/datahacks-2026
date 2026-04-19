"""Build a NetCDF file from CalCOFI Cast + Bottle CSVs.

Coords: lat, lon, time (per-profile)
Vars: Temp (T_degC), Salinity (Salnty), indexed by (profile, depth)
"""
import os
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr

from project_paths import (
    PROCESSED_CALCOFI_LEGACY_NC,
    PROCESSED_CALCOFI_NC,
    RAW_CALCOFI_BASE_DIR,
)


BASE = RAW_CALCOFI_BASE_DIR
CAST_CSV = BASE / "194903-202105_Cast.csv"
BOTTLE_CSV = BASE / "194903-202105_Bottle.csv"
OUT_NC = PROCESSED_CALCOFI_NC


def _parse_time(series: pd.Series) -> pd.Series:
    """Return hours-of-day as float; handles HH:MM, HHMM, blank."""
    s = series.astype(str).str.strip().str.replace(":", "", regex=False)
    s = s.where(s.str.fullmatch(r"\d{1,4}"), other="")
    # Pad to 4 digits so "930" -> "0930"
    padded = s.str.zfill(4).replace("0000", "0000")
    hh = pd.to_numeric(padded.str[:2], errors="coerce")
    mm = pd.to_numeric(padded.str[2:], errors="coerce")
    hours = hh + mm / 60.0
    return hours.fillna(0.0)


def load_casts() -> pd.DataFrame:
    cols = ["Cst_Cnt", "Date", "Time", "Lat_Dec", "Lon_Dec"]
    df = pd.read_csv(CAST_CSV, usecols=cols, encoding="latin-1", low_memory=False)
    date = pd.to_datetime(df["Date"], format="%m/%d/%Y", errors="coerce")
    hours = _parse_time(df["Time"])
    dt = date + pd.to_timedelta(hours, unit="h")
    df = df.assign(time=dt).dropna(subset=["time", "Lat_Dec", "Lon_Dec"])
    return df[["Cst_Cnt", "time", "Lat_Dec", "Lon_Dec"]]


def load_bottles() -> pd.DataFrame:
    cols = ["Cst_Cnt", "Depthm", "T_degC", "Salnty"]
    df = pd.read_csv(BOTTLE_CSV, usecols=cols, encoding="latin-1", low_memory=False)
    return df.dropna(subset=["Depthm"])


def build_dataset() -> xr.Dataset:
    casts = load_casts()
    bottles = load_bottles()
    print(f"casts: {len(casts)}  bottles: {len(bottles)}")
    merged = bottles.merge(casts, on="Cst_Cnt", how="inner")
    print(f"merged rows: {len(merged)}  "
          f"time range: {merged['time'].min()} -> {merged['time'].max()}")

    profiles = (
        merged[["Cst_Cnt", "time", "Lat_Dec", "Lon_Dec"]]
        .drop_duplicates("Cst_Cnt")
        .sort_values("time")
        .reset_index(drop=True)
    )
    profile_idx = {c: i for i, c in enumerate(profiles["Cst_Cnt"].values)}

    depths = np.sort(merged["Depthm"].unique())
    depth_idx = {d: i for i, d in enumerate(depths)}

    n_prof, n_dep = len(profiles), len(depths)
    temp = np.full((n_prof, n_dep), np.nan, dtype=np.float32)
    sal = np.full((n_prof, n_dep), np.nan, dtype=np.float32)

    pi = merged["Cst_Cnt"].map(profile_idx).to_numpy()
    di = merged["Depthm"].map(depth_idx).to_numpy()
    temp[pi, di] = merged["T_degC"].to_numpy(dtype=np.float32)
    sal[pi, di] = merged["Salnty"].to_numpy(dtype=np.float32)

    ds = xr.Dataset(
        data_vars={
            "Temp": (("profile", "depth"), temp, {"units": "degC", "long_name": "Sea water temperature"}),
            "Salinity": (("profile", "depth"), sal, {"units": "PSU", "long_name": "Practical salinity"}),
        },
        coords={
            "time": ("profile", profiles["time"].to_numpy()),
            "lat": ("profile", profiles["Lat_Dec"].to_numpy(dtype=np.float32), {"units": "degrees_north"}),
            "lon": ("profile", profiles["Lon_Dec"].to_numpy(dtype=np.float32), {"units": "degrees_east"}),
            "depth": ("depth", depths.astype(np.float32), {"units": "m", "positive": "down"}),
        },
        attrs={"title": "CalCOFI Temperature and Salinity", "source": "CalCOFI 1949-2021 Bottle+Cast CSVs"},
    )
    return ds


def write_dataset(ds: xr.Dataset, out_nc: Path) -> None:
    tmp_nc = out_nc.with_suffix(".tmp.nc")
    enc = {v: {"zlib": True, "complevel": 4} for v in ("Temp", "Salinity")}

    if tmp_nc.exists():
        tmp_nc.unlink()

    try:
        ds.to_netcdf(tmp_nc, encoding=enc)
        os.replace(tmp_nc, out_nc)
    except PermissionError as exc:
        if tmp_nc.exists():
            tmp_nc.unlink()
        raise PermissionError(
            f"Could not write {out_nc}. On Windows this usually means the file is "
            "still open in another Python session, notebook, or viewer. Close any "
            f"existing handles to {PROCESSED_CALCOFI_LEGACY_NC.name} and rerun."
        ) from exc
    finally:
        ds.close()


def main() -> None:
    ds = build_dataset()
    write_dataset(ds, OUT_NC)
    print(f"Wrote {OUT_NC} ({dict(ds.sizes)})")


if __name__ == "__main__":
    main()
    
    
