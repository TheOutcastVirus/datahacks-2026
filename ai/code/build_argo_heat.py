"""Build a monthly NE-Pacific 0-700 dbar heat-content anomaly series from
the EasyOneArgoTSLite tarball without extracting it to disk.

Strategy:
1. Stream the top-level index CSV out of the tarball (one small file).
2. Filter to a NE Pacific bounding box + date range.
3. Stream the tarball once; for each member that matches a filtered profile,
   read bytes in memory, parse temperature/pressure, trapezoidal-integrate
   temperature from the surface to 700 dbar, record (date, heat700).
4. Bin monthly, subtract monthly climatology, write CSV.

Never writes per-profile files to disk. Peak memory is bounded by the number
of filtered profiles (O(10^5) floats at worst).
"""
from __future__ import annotations

import io
import re
import tarfile
import time

import numpy as np
import pandas as pd

from project_paths import PROCESSED_ARGO_CSV, RAW_ARGO_TARBALL


TARBALL = RAW_ARGO_TARBALL
OUT_CSV = PROCESSED_ARGO_CSV

# NE Pacific box offshore of La Jolla. Broad on purpose: we want basin-scale
# thermal signal, not nearshore noise (CalCOFI already covers nearshore).
LAT_MIN, LAT_MAX = 25.0, 40.0
LON_MIN, LON_MAX = -140.0, -118.0
# Match the sea-level / CalCOFI overlap window; Argo only starts ~2002.
DATE_MIN = pd.Timestamp("2002-01-01")
DATE_MAX = pd.Timestamp("2023-01-01")

INTEGRATION_DEPTH_DBAR = 700.0
MIN_TOP_DBAR = 20.0     # reject profiles that don't reach close to the surface
MIN_BOTTOM_DBAR = 500.0  # reject profiles that don't go deep enough


def _resolve_index_member_name(tar: tarfile.TarFile) -> str:
    for member in tar:
        if member.name.endswith("EasyOneArgoTSLite_index.csv"):
            return member.name
    raise RuntimeError("Index CSV not found in tarball.")


def load_filtered_index() -> pd.DataFrame:
    print(f"Streaming index from {TARBALL.name} ...")
    # Open once just for the index (small, near the end of the archive but we
    # only need one file). Use streaming mode so we don't build a full member list.
    with tarfile.open(TARBALL, mode="r|gz") as tar:
        for member in tar:
            if not member.name.endswith("EasyOneArgoTSLite_index.csv"):
                continue
            buf = tar.extractfile(member)
            assert buf is not None
            raw = buf.read()
            break
        else:
            raise RuntimeError("Index CSV not found.")

    # Strip comment lines (start with '#'); keep the header + data rows.
    text = raw.decode("utf-8", errors="replace")
    non_comment = "\n".join(
        line for line in text.splitlines() if not line.startswith("#")
    )
    idx = pd.read_csv(io.StringIO(non_comment))
    print(f"Index rows total: {len(idx):,}")

    idx["profile_date"] = pd.to_datetime(idx["profile_date"], utc=True).dt.tz_localize(None)
    mask = (
        idx["profile_latitude"].between(LAT_MIN, LAT_MAX)
        & idx["profile_longitude"].between(LON_MIN, LON_MAX)
        & idx["profile_date"].between(DATE_MIN, DATE_MAX)
    )
    sub = idx.loc[mask].copy()
    print(
        f"Filtered to box [{LAT_MIN},{LAT_MAX}] x [{LON_MIN},{LON_MAX}], "
        f"{DATE_MIN.date()} -> {DATE_MAX.date()}: {len(sub):,} profiles"
    )
    return sub


def _expected_member_name(row: pd.Series) -> str:
    # Direction: 'A' ascending (default), 'D' descending -> filename suffix.
    suffix = "D" if str(row["direction_of_profile"]).strip() == "D" else ""
    cycle = int(row["cycle_number"])
    platform = int(row["platform_number"])
    # File naming convention: <platform>_<cycle>[D]_EasyTSLite.csv
    return f"{platform}_{cycle:03d}{suffix}_EasyTSLite.csv"


def _parse_profile_csv(raw: bytes) -> np.ndarray | None:
    """Return an (n, 2) array of [pressure_dbar, temperature_C] or None."""
    text = raw.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 3:
        return None
    # First non-comment line is the header with units in parentheses.
    data_lines = lines[1:]
    rows = []
    for ln in data_lines:
        parts = ln.split(",")
        if len(parts) < 2:
            continue
        p_raw, t_raw = parts[0].strip(), parts[1].strip()
        if not p_raw or not t_raw:
            continue
        try:
            p = float(p_raw)
            t = float(t_raw)
        except ValueError:
            continue
        if not (np.isfinite(p) and np.isfinite(t)):
            continue
        rows.append((p, t))
    if len(rows) < 3:
        return None
    return np.asarray(rows, dtype=np.float64)


def _heat_content_proxy(profile: np.ndarray, depth_dbar: float) -> float | None:
    """Depth-integrated temperature (deg C * dbar) from surface to `depth_dbar`.

    This is a proxy for heat content — proportional up to a rho*Cp constant
    that cancels out when we later compute anomalies.
    """
    p = profile[:, 0]
    t = profile[:, 1]
    # Require reasonable coverage of the integration window.
    if p[0] > MIN_TOP_DBAR:
        return None
    if p[-1] < MIN_BOTTOM_DBAR:
        return None
    # Clip to [0, depth_dbar]; linearly interpolate the endpoints if needed.
    mask = p <= depth_dbar
    if mask.sum() < 3:
        return None
    p_clip = p[mask]
    t_clip = t[mask]
    # Extend to exactly `depth_dbar` if we have points bracketing it.
    if p_clip[-1] < depth_dbar and p[-1] >= depth_dbar:
        next_idx = np.searchsorted(p, depth_dbar)
        p_below, t_below = p[next_idx - 1], t[next_idx - 1]
        p_above, t_above = p[next_idx], t[next_idx]
        frac = (depth_dbar - p_below) / (p_above - p_below)
        t_at_depth = t_below + frac * (t_above - t_below)
        p_clip = np.append(p_clip, depth_dbar)
        t_clip = np.append(t_clip, t_at_depth)
    trapz = getattr(np, "trapezoid", None) or np.trapz  # numpy 2.0 renamed trapz
    return float(trapz(t_clip, p_clip))


def stream_profiles(wanted: dict[str, pd.Timestamp]) -> pd.DataFrame:
    """One pass over the tarball; collect heat-content for wanted members."""
    print(f"Streaming tarball for {len(wanted):,} target profiles ...")
    results = []
    matched = 0
    missing = 0
    parsed = 0
    skipped_coverage = 0
    start = time.time()
    pattern = re.compile(r"([^/]+)$")

    with tarfile.open(TARBALL, mode="r|gz") as tar:
        for i, member in enumerate(tar):
            if not member.isreg():
                continue
            if not member.name.endswith("_EasyTSLite.csv"):
                continue
            m = pattern.search(member.name)
            if not m:
                continue
            fname = m.group(1)
            if fname not in wanted:
                continue
            matched += 1
            buf = tar.extractfile(member)
            if buf is None:
                missing += 1
                continue
            profile = _parse_profile_csv(buf.read())
            if profile is None:
                missing += 1
                continue
            hc = _heat_content_proxy(profile, INTEGRATION_DEPTH_DBAR)
            if hc is None:
                skipped_coverage += 1
                continue
            parsed += 1
            results.append((wanted[fname], hc))

            if matched % 2000 == 0:
                elapsed = time.time() - start
                print(
                    f"  matched={matched:,}  parsed={parsed:,}  "
                    f"skipped_coverage={skipped_coverage:,}  "
                    f"elapsed={elapsed:.1f}s"
                )

    print(
        f"Done. matched={matched:,} parsed={parsed:,} "
        f"skipped_coverage={skipped_coverage:,} missing={missing:,}"
    )
    df = pd.DataFrame(results, columns=["profile_date", "heat700"])
    return df


def main() -> None:
    idx = load_filtered_index()
    wanted: dict[str, pd.Timestamp] = {}
    for _, row in idx.iterrows():
        wanted[_expected_member_name(row)] = row["profile_date"]
    if not wanted:
        raise SystemExit("No profiles matched the filter.")

    raw = stream_profiles(wanted)
    if raw.empty:
        raise SystemExit("No profiles parsed from tarball.")

    raw = raw.set_index("profile_date").sort_index()
    # Monthly mean over the box.
    monthly = raw["heat700"].resample("MS").mean().to_frame("heat700")
    monthly["n_profiles"] = raw["heat700"].resample("MS").count()
    climatology = monthly.groupby(monthly.index.month)["heat700"].transform("mean")
    monthly["heat700_anomaly"] = monthly["heat700"] - climatology
    monthly.index.name = "time"
    monthly.to_csv(OUT_CSV)
    print(f"Wrote {OUT_CSV}  ({len(monthly)} months, non-null heat700={monthly['heat700'].notna().sum()})")


if __name__ == "__main__":
    main()
