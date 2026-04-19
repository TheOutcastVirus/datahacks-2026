"""PLY hazard analyzer.

Reads a Gaussian-splat or mesh PLY, computes geometric hazard proxies, and
writes a hazards JSON consumed by the frontend SplatViewer.

Detections (all are geometric proxies — framed cautiously in copy):
  - tall_structure: vertical peaks above a height percentile, clustered
  - flood_exposed: mass fraction below a flood-plane Y for a scenario
  - erosion_proxy: high local height gradient on ground-dominated terrain

The script intentionally mirrors the header parsing in
`frontend/public/splat/main.js :: processPlyBuffer` so world space matches the
PLY branch in `SplatViewer.tsx`.

Usage:
    python scripts/ply_hazards.py INPUT.ply OUTPUT.json [--flood-y 0.2]
"""

from __future__ import annotations

import argparse
import json
import string
import struct
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import numpy as np


@dataclass
class Hazard:
    id: str
    label: str
    position: list[float]
    severity: float
    metrics: dict
    summary: str


def _parse_header(buf: bytes) -> tuple[int, int, list[tuple[str, str]]]:
    header_end = buf.find(b"end_header\n")
    if header_end < 0:
        raise ValueError("PLY: end_header not found")
    header = buf[:header_end].decode("ascii", errors="ignore").splitlines()
    count = 0
    props: list[tuple[str, str]] = []
    for line in header:
        if line.startswith("element vertex"):
            count = int(line.split()[-1])
        elif line.startswith("property"):
            parts = line.split()
            props.append((parts[1], parts[2]))
    return header_end + len(b"end_header\n"), count, props


_TYPE_MAP = {
    "float": ("f", 4),
    "float32": ("f", 4),
    "double": ("d", 8),
    "uchar": ("B", 1),
    "uint8": ("B", 1),
    "int": ("i", 4),
    "int32": ("i", 4),
    "short": ("h", 2),
    "ushort": ("H", 2),
}


def load_ply_points(path: Path) -> np.ndarray:
    data = path.read_bytes()
    body_start, count, props = _parse_header(data)
    fmt = "<" + "".join(_TYPE_MAP[p[0]][0] for p in props)
    stride = sum(_TYPE_MAP[p[0]][1] for p in props)
    names = [p[1] for p in props]
    xi, yi, zi = names.index("x"), names.index("y"), names.index("z")
    view = np.frombuffer(data, dtype=np.uint8, count=count * stride, offset=body_start)
    view = view.reshape(count, stride)
    # decode x,y,z columns only to keep memory small
    offsets = np.cumsum([0] + [_TYPE_MAP[p[0]][1] for p in props])
    def col(i: int) -> np.ndarray:
        off = offsets[i]
        raw = view[:, off : off + 4].tobytes()
        return np.frombuffer(raw, dtype=np.float32, count=count)
    return np.column_stack([col(xi), col(yi), col(zi)]).astype(np.float64)


def _letter_ids(n: int) -> list[str]:
    letters = list(string.ascii_uppercase)
    return letters[:n] if n <= 26 else [f"{letters[i // 26 - 1]}{letters[i % 26]}" for i in range(n)]


def detect_tall_structures(xyz: np.ndarray, grid: int = 64, top_k: int = 3) -> list[Hazard]:
    xs, ys, zs = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    xmin, xmax = xs.min(), xs.max()
    zmin, zmax = zs.min(), zs.max()
    ix = np.clip(((xs - xmin) / max(xmax - xmin, 1e-9) * (grid - 1)).astype(int), 0, grid - 1)
    iz = np.clip(((zs - zmin) / max(zmax - zmin, 1e-9) * (grid - 1)).astype(int), 0, grid - 1)
    height = np.full((grid, grid), -np.inf)
    np.maximum.at(height, (ix, iz), ys)
    flat = height.flatten()
    valid = np.isfinite(flat)
    if not valid.any():
        return []
    threshold = np.percentile(flat[valid], 97)
    candidates = np.argwhere(height >= threshold)
    # rank by height, keep spatially separated top_k
    candidates = sorted(candidates, key=lambda rc: -height[rc[0], rc[1]])
    picked: list[tuple[int, int]] = []
    for r, c in candidates:
        if all(abs(r - pr) + abs(c - pc) > grid // 8 for pr, pc in picked):
            picked.append((r, c))
        if len(picked) >= top_k:
            break
    y_range = float(ys.max() - ys.min()) or 1.0
    hazards: list[Hazard] = []
    for (r, c) in picked:
        peak_y = float(height[r, c])
        peak_x = float(xmin + (r + 0.5) / grid * (xmax - xmin))
        peak_z = float(zmin + (c + 0.5) / grid * (zmax - zmin))
        extent = (peak_y - float(ys.min())) / y_range
        hazards.append(Hazard(
            id="",
            label="tall_structure",
            position=[peak_x, peak_y, peak_z],
            severity=float(min(1.0, extent)),
            metrics={"peakHeight": round(peak_y, 4), "verticalExtentFraction": round(extent, 3)},
            summary="Tall structure: vertical peak rising above surrounding terrain.",
        ))
    return hazards


def detect_flood_exposed(xyz: np.ndarray, flood_y: float, grid: int = 48, top_k: int = 2) -> list[Hazard]:
    xs, ys, zs = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    xmin, xmax = xs.min(), xs.max()
    zmin, zmax = zs.min(), zs.max()
    ix = np.clip(((xs - xmin) / max(xmax - xmin, 1e-9) * (grid - 1)).astype(int), 0, grid - 1)
    iz = np.clip(((zs - zmin) / max(zmax - zmin, 1e-9) * (grid - 1)).astype(int), 0, grid - 1)
    below = ys < flood_y
    total = np.zeros((grid, grid), dtype=np.int64)
    sub = np.zeros((grid, grid), dtype=np.int64)
    np.add.at(total, (ix, iz), 1)
    np.add.at(sub, (ix[below], iz[below]), 1)
    frac = np.where(total > 0, sub / np.maximum(total, 1), 0.0)
    # pick most-exposed cells with enough points
    mask = total > np.percentile(total[total > 0], 60) if (total > 0).any() else total > 0
    candidates = np.argwhere(mask & (frac > 0.4))
    candidates = sorted(candidates, key=lambda rc: -frac[rc[0], rc[1]])
    picked: list[tuple[int, int]] = []
    for r, c in candidates:
        if all(abs(r - pr) + abs(c - pc) > grid // 8 for pr, pc in picked):
            picked.append((r, c))
        if len(picked) >= top_k:
            break
    hazards: list[Hazard] = []
    for (r, c) in picked:
        cell_x = float(xmin + (r + 0.5) / grid * (xmax - xmin))
        cell_z = float(zmin + (c + 0.5) / grid * (zmax - zmin))
        fraction = float(frac[r, c])
        hazards.append(Hazard(
            id="",
            label="flood_exposed",
            position=[cell_x, flood_y, cell_z],
            severity=float(min(1.0, fraction)),
            metrics={"belowFloodFraction": round(fraction, 3), "floodY": round(flood_y, 4)},
            summary="Flood-exposed: sits below the modeled flood plane in this scenario.",
        ))
    return hazards


def detect_erosion_proxy(xyz: np.ndarray, grid: int = 48, top_k: int = 2) -> list[Hazard]:
    xs, ys, zs = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    xmin, xmax = xs.min(), xs.max()
    zmin, zmax = zs.min(), zs.max()
    ix = np.clip(((xs - xmin) / max(xmax - xmin, 1e-9) * (grid - 1)).astype(int), 0, grid - 1)
    iz = np.clip(((zs - zmin) / max(zmax - zmin, 1e-9) * (grid - 1)).astype(int), 0, grid - 1)
    height = np.full((grid, grid), np.nan)
    np.maximum.at(np.nan_to_num(height, nan=-np.inf), (ix, iz), ys)  # init trick
    # recompute properly
    h = np.full((grid, grid), -np.inf)
    np.maximum.at(h, (ix, iz), ys)
    valid = np.isfinite(h)
    gy, gx = np.gradient(np.where(valid, h, 0.0))
    mag = np.sqrt(gx ** 2 + gy ** 2) * valid
    if not mag.any():
        return []
    thresh = np.percentile(mag[mag > 0], 95)
    candidates = sorted(np.argwhere(mag >= thresh), key=lambda rc: -mag[rc[0], rc[1]])
    picked: list[tuple[int, int]] = []
    for r, c in candidates:
        if all(abs(r - pr) + abs(c - pc) > grid // 8 for pr, pc in picked):
            picked.append((r, c))
        if len(picked) >= top_k:
            break
    mag_max = float(mag.max()) or 1.0
    hazards: list[Hazard] = []
    for (r, c) in picked:
        cell_x = float(xmin + (r + 0.5) / grid * (xmax - xmin))
        cell_z = float(zmin + (c + 0.5) / grid * (zmax - zmin))
        cell_y = float(h[r, c]) if np.isfinite(h[r, c]) else float(ys.mean())
        hazards.append(Hazard(
            id="",
            label="erosion_proxy",
            position=[cell_x, cell_y, cell_z],
            severity=float(min(1.0, mag[r, c] / mag_max)),
            metrics={"gradientMagnitude": round(float(mag[r, c]), 4)},
            summary="Possible erosion-prone terrain: steep local height gradient (geometric proxy).",
        ))
    return hazards


def assign_ids(hazards: Iterable[Hazard]) -> list[Hazard]:
    out = list(hazards)
    out.sort(key=lambda h: -h.severity)
    for hz, letter in zip(out, _letter_ids(len(out))):
        hz.id = letter
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--flood-y", type=float, default=None, help="Flood plane Y (world units). Defaults to 20%% bbox.")
    args = ap.parse_args()

    xyz = load_ply_points(args.input)
    y_min, y_max = float(xyz[:, 1].min()), float(xyz[:, 1].max())
    flood_y = args.flood_y if args.flood_y is not None else y_min + 0.2 * (y_max - y_min)

    hazards = (
        detect_tall_structures(xyz)
        + detect_flood_exposed(xyz, flood_y)
        + detect_erosion_proxy(xyz)
    )
    hazards = assign_ids(hazards)

    payload = {
        "version": 1,
        "source": args.input.name,
        "bbox": {"yMin": y_min, "yMax": y_max, "floodY": flood_y},
        "hazards": [asdict(h) for h in hazards],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))
    print(f"wrote {len(hazards)} hazards → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
