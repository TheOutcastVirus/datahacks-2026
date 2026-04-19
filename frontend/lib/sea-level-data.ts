import projectionsCsv from '../public/projections.csv';

type ProjectionRow = {
  year: number;
  high: number;
};

function parseProjectionRows(csvText: string): ProjectionRow[] {
  return csvText
    .trim()
    .split(/\r?\n/)
    .slice(1)
    .map((line) => {
      const [year, , , high] = line.split(',');

      return {
        year: Number.parseInt(year, 10),
        high: Number.parseFloat(high),
      };
    })
    .filter((row) => Number.isFinite(row.year) && Number.isFinite(row.high))
    .sort((a, b) => a.year - b.year);
}

function buildSeaLevelData(rows: ProjectionRow[]): Record<number, number> {
  return rows.reduce<Record<number, number>>(
    (data, row) => {
      data[row.year] = row.high;
      return data;
    },
    { 2026: 0 },
  );
}

const projectionRows = parseProjectionRows(projectionsCsv);
const SEA_LEVEL_DATA: Record<number, number> = buildSeaLevelData(projectionRows);
const LAST_DATA_YEAR = projectionRows[projectionRows.length - 1]?.year ?? 2026;
const LAST_DATA_VALUE = SEA_LEVEL_DATA[LAST_DATA_YEAR] ?? 0;
const PREVIOUS_DATA_VALUE = SEA_LEVEL_DATA[LAST_DATA_YEAR - 1] ?? LAST_DATA_VALUE;

// Linear rate extrapolated from the last two projected years in projections.csv.
const EXTRAPOLATION_RATE_M_PER_YEAR = LAST_DATA_VALUE - PREVIOUS_DATA_VALUE;

/**
 * Returns projected sea level rise in meters using the high-end CSV values.
 * Years up to 2026 clamp to 0, then values interpolate within the CSV range
 * and extrapolate linearly beyond it.
 */
export function getSeaLevel(year: number): number {
  if (year <= 2026) return 0;
  if (year > LAST_DATA_YEAR) {
    return LAST_DATA_VALUE + EXTRAPOLATION_RATE_M_PER_YEAR * (year - LAST_DATA_YEAR);
  }

  const lo = Math.floor(year);
  const hi = Math.ceil(year);

  if (lo === hi) return SEA_LEVEL_DATA[lo] ?? 0;

  const frac = year - lo;
  return (SEA_LEVEL_DATA[lo] ?? 0) * (1 - frac) + (SEA_LEVEL_DATA[hi] ?? 0) * frac;
}

export { SEA_LEVEL_DATA };
