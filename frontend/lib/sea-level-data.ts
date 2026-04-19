type ProjectionRow = {
  year: number;
  high: number;
};

type SeaLevelDataset = {
  data: Record<number, number>;
  lastYear: number;
  extrapolationRate: number;
};

let seaLevelDatasetPromise: Promise<SeaLevelDataset> | null = null;

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

function buildSeaLevelDataset(rows: ProjectionRow[]): SeaLevelDataset {
  const data = rows.reduce<Record<number, number>>(
    (accumulator, row) => {
      accumulator[row.year] = row.high;
      return accumulator;
    },
    { 2026: 0 },
  );
  const lastYear = rows[rows.length - 1]?.year ?? 2026;
  const lastValue = data[lastYear] ?? 0;
  const previousValue = data[lastYear - 1] ?? lastValue;

  return {
    data,
    lastYear,
    extrapolationRate: lastValue - previousValue,
  };
}

async function loadSeaLevelDataset(): Promise<SeaLevelDataset> {
  if (!seaLevelDatasetPromise) {
    seaLevelDatasetPromise = fetch('/projections.csv', { cache: 'force-cache' })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Failed to load sea-level projections: ${response.status}`);
        }

        return response.text();
      })
      .then((csvText) => buildSeaLevelDataset(parseProjectionRows(csvText)));
  }

  return seaLevelDatasetPromise;
}

/**
 * Returns projected sea level rise in meters using the high-end CSV values.
 * Years up to 2026 clamp to 0, then values interpolate within the CSV range
 * and extrapolate linearly beyond it.
 */
export async function getSeaLevel(year: number): Promise<number> {
  if (year <= 2026) return 0;

  const { data, lastYear, extrapolationRate } = await loadSeaLevelDataset();
  const lastValue = data[lastYear] ?? 0;

  if (year > lastYear) {
    return lastValue + extrapolationRate * (year - lastYear);
  }

  const lo = Math.floor(year);
  const hi = Math.ceil(year);

  if (lo === hi) return data[lo] ?? 0;

  const frac = year - lo;
  return (data[lo] ?? 0) * (1 - frac) + (data[hi] ?? 0) * frac;
}

export async function preloadSeaLevelData(): Promise<void> {
  await loadSeaLevelDataset();
}
