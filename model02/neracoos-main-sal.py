from __future__ import annotations

import argparse
import io
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

BASE_TABLEDAP_URL = "https://data.neracoos.org/erddap/tabledap"
DEFAULT_STATIONS = ("B01", "E01", "F01", "M01", "N01")
DEFAULT_COLUMNS = (
    "station",
    "time",
    "depth",
    "latitude",
    "longitude",
    "salinity",
    "salinity_qc",
    "salinity_qc_agg",
)
DEFAULT_OUTPUT = Path("data/neracoos_salinity_1950_present.csv")
USER_AGENT = "Sojs NERACOOS salinity fetcher/1.0"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch yearly NERACOOS salinity data for one or more buoy stations and "
            "combine the results into a single CSV."
        )
    )
    parser.add_argument(
        "--stations",
        nargs="+",
        default=list(DEFAULT_STATIONS),
        help=(
            "Station ids to fetch. Defaults to B01 E01 F01 M01 N01. "
            "Each station maps to <station>_ocean_agg on the NERACOOS ERDDAP server."
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1950,
        help="First year to request. Default: 1950.",
    )
    parser.add_argument(
        "--end-date",
        default=date.today().isoformat(),
        help="Inclusive end date in YYYY-MM-DD format. Default: today.",
    )
    parser.add_argument(
        "--chunk-years",
        type=int,
        default=1,
        help="Number of years per request window. Default: 1.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds for each request. Default: 120.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retry attempts per failed request. Default: 3.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.0,
        help="Pause after each successful request inside a worker. Default: 0.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=8,
        help="Maximum number of concurrent HTTP requests. Default: 8.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Combined CSV output path. Default: {DEFAULT_OUTPUT}",
    )
    return parser.parse_args(argv)


def parse_end_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid --end-date {value!r}; expected YYYY-MM-DD.") from exc


def normalize_station(station: str) -> str:
    cleaned = station.strip().upper()
    if not re.fullmatch(r"[A-Z]\d{2}", cleaned):
        raise ValueError(
            f"Invalid station id {station!r}. Expected values like B01 or E01."
        )
    return cleaned


def dataset_id_for_station(station: str) -> str:
    return f"{normalize_station(station)}_ocean_agg"


def yearly_windows(
    start_year: int,
    end_date_inclusive: date,
    chunk_years: int,
) -> Iterable[tuple[date, date]]:
    if chunk_years <= 0:
        raise ValueError("--chunk-years must be positive.")
    if start_year < 1:
        raise ValueError("--start-year must be at least 1.")

    current = date(start_year, 1, 1)
    end_exclusive = end_date_inclusive + timedelta(days=1)
    while current < end_exclusive:
        next_year_start = date(current.year + chunk_years, 1, 1)
        window_end = min(next_year_start, end_exclusive)
        yield current, window_end
        current = window_end


def build_query_url(dataset_id: str, window_start: date, window_end: date) -> str:
    start_text = f"{window_start.isoformat()}T00:00:00Z"
    end_text = f"{window_end.isoformat()}T00:00:00Z"
    query_parts = [
        ",".join(DEFAULT_COLUMNS),
        f"time>={start_text}",
        f"time<{end_text}",
        'orderBy("time,depth")',
    ]
    encoded_query = "&".join(quote(part, safe="") for part in query_parts)
    return f"{BASE_TABLEDAP_URL}/{dataset_id}.csvp?{encoded_query}"


def normalize_columns(columns: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for column in columns:
        cleaned = re.sub(r"\s+\([^)]*\)$", "", str(column).strip())
        cleaned = re.sub(r"[^0-9A-Za-z]+", "_", cleaned).strip("_").lower()
        normalized.append(cleaned)
    return normalized


def fetch_csv(url: str, *, timeout: int, retries: int) -> pd.DataFrame:
    headers = {"User-Agent": USER_AGENT}
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code == 404:
                print(
                    f"Skipping missing window (404): {url}",
                    file=sys.stderr,
                )
                return pd.DataFrame(columns=DEFAULT_COLUMNS)
            last_error = exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
        else:
            if "Your query produced no matching results" in body:
                return pd.DataFrame(columns=DEFAULT_COLUMNS)
            if body.lstrip().startswith("Error {"):
                raise RuntimeError(body.strip())

            frame = pd.read_csv(io.StringIO(body))
            frame.columns = normalize_columns(frame.columns)
            return frame

        if attempt < retries:
            time.sleep(min(5, attempt))

    raise RuntimeError(f"Failed to fetch URL after {retries} attempts: {url}") from last_error


def prepare_frame(frame: pd.DataFrame, dataset_id: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "station",
                "time",
                "depth",
                "latitude",
                "longitude",
                "salinity",
                "salinity_qc",
                "salinity_qc_agg",
                "source_dataset",
            ]
        )

    if "station" not in frame.columns:
        station_name = dataset_id.split("_", 1)[0]
        frame["station"] = station_name

    frame["source_dataset"] = dataset_id
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    for column in ("depth", "latitude", "longitude", "salinity", "salinity_qc", "salinity_qc_agg"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["time", "salinity"])
    return frame[
        [
            "station",
            "time",
            "depth",
            "latitude",
            "longitude",
            "salinity",
            "salinity_qc",
            "salinity_qc_agg",
            "source_dataset",
        ]
    ]


def fetch_window_salinity(
    station: str,
    window_start: date,
    window_end: date,
    *,
    timeout: int,
    retries: int,
    pause_seconds: float,
) -> pd.DataFrame:
    dataset_id = dataset_id_for_station(station)
    url = build_query_url(dataset_id, window_start, window_end)
    print(
        f"[{station}] fetching {window_start.isoformat()} -> "
        f"{(window_end - timedelta(days=1)).isoformat()}",
        file=sys.stderr,
    )
    frame = prepare_frame(
        fetch_csv(url, timeout=timeout, retries=retries),
        dataset_id=dataset_id,
    )
    if pause_seconds > 0:
        time.sleep(pause_seconds)
    return frame


def fetch_all_stations(
    stations: Sequence[str],
    *,
    start_year: int,
    end_date_inclusive: date,
    chunk_years: int,
    timeout: int,
    retries: int,
    pause_seconds: float,
    max_concurrency: int,
) -> pd.DataFrame:
    if max_concurrency <= 0:
        raise ValueError("--max-concurrency must be positive.")

    windows = list(yearly_windows(start_year, end_date_inclusive, chunk_years))
    frames: list[pd.DataFrame] = []

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        future_map = {
            executor.submit(
                fetch_window_salinity,
                station,
                window_start,
                window_end,
                timeout=timeout,
                retries=retries,
                pause_seconds=pause_seconds,
            ): (station, window_start, window_end)
            for station in stations
            for window_start, window_end in windows
        }

        for future in as_completed(future_map):
            station, window_start, window_end = future_map[future]
            try:
                frame = future.result()
            except Exception as exc:
                raise RuntimeError(
                    f"Failed while fetching {station} for "
                    f"{window_start.isoformat()} -> "
                    f"{(window_end - timedelta(days=1)).isoformat()}"
                ) from exc
            if not frame.empty:
                frames.append(frame)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if combined.empty:
        return pd.DataFrame(
            columns=[
                "station",
                "time",
                "depth",
                "latitude",
                "longitude",
                "salinity",
                "salinity_qc",
                "salinity_qc_agg",
                "source_dataset",
            ]
        )

    combined = combined.drop_duplicates(subset=["station", "time", "depth"])
    combined = combined.sort_values(["station", "time", "depth"], kind="stable")
    combined["time"] = combined["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return combined.reset_index(drop=True)


def save_csv(frame: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    stations = [normalize_station(station) for station in args.stations]
    end_date_inclusive = parse_end_date(args.end_date)
    if end_date_inclusive > datetime.now(UTC).date():
        raise ValueError("--end-date cannot be in the future.")

    combined = fetch_all_stations(
        stations,
        start_year=args.start_year,
        end_date_inclusive=end_date_inclusive,
        chunk_years=args.chunk_years,
        timeout=args.timeout,
        retries=args.retries,
        pause_seconds=args.pause_seconds,
        max_concurrency=args.max_concurrency,
    )
    save_csv(combined, args.output)

    print(f"Saved {len(combined):,} rows to {args.output.resolve()}")
    if not combined.empty:
        print(
            "Stations: "
            + ", ".join(sorted(combined["station"].dropna().astype(str).unique()))
        )
        print(f"Time range: {combined['time'].iloc[0]} -> {combined['time'].iloc[-1]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
