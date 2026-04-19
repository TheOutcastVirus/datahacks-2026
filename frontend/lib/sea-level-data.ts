// Sea level rise relative to 2026 baseline, derived from NOAA tidal predictions.
// Source: predicted_MSL + predicted_trend from sla_prediction_timeseries.csv,
// averaged per year, normalized so 2026 = 0.
const SEA_LEVEL_DATA: Record<number, number> = {
  2026: 0.0,
  2027: 0.0577,
  2028: 0.1416,
  2029: 0.2604,
  2030: 0.3746,
  2031: 0.4157,
  2032: 0.4397,
  2033: 0.4631,
  2034: 0.4859,
  2035: 0.5093,
  2036: 0.5322,
  2037: 0.5556,
  2038: 0.5784,
  2039: 0.6012,
  2040: 0.6247,
  2041: 0.6475,
  2042: 0.6703,
  2043: 0.6938,
  2044: 0.7166,
  2045: 0.7394,
  2046: 0.7629,
  2047: 0.7857,
  2048: 0.8085,
  2049: 0.8319,
  2050: 0.8548,
  2051: 0.8776,
  2052: 0.9004,
  2053: 0.9239,
  2054: 0.9467,
  2055: 0.9695,
  2056: 0.9930,
  2057: 1.0158,
  2058: 1.0386,
  2059: 1.0621,
  2060: 1.0849,
  2061: 1.1077,
  2062: 1.1311,
  2063: 1.1540,
  2064: 1.1768,
  2065: 1.2002,
  2066: 1.2231,
  2067: 1.2459,
  2068: 1.2693,
  2069: 1.2922,
  2070: 1.3150,
};

// Linear rate extrapolated from 2069–2070 trend for years beyond model coverage.
const EXTRAPOLATION_RATE_M_PER_YEAR = 0.02284;
const LAST_DATA_YEAR = 2070;
const LAST_DATA_VALUE = SEA_LEVEL_DATA[LAST_DATA_YEAR];

/**
 * Returns predicted sea level rise in meters relative to the 2026 baseline.
 * Interpolates between known years; extrapolates linearly beyond 2070.
 * Returns 0 for years before 2026.
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
