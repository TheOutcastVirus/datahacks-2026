// Sea level rise relative to 2026 baseline, derived from NOAA tidal predictions.
// Source: predicted_MSL + predicted_trend from sla_prediction_timeseries.csv,
// averaged per year, normalized so 2026 = 0.
const SEA_LEVEL_DATA: Record<number, number> = {
  2026: 0.0,
  2027: 0.0101,
  2028: 0.0248,
  2029: 0.0456,
  2030: 0.0656,
  2031: 0.0728,
  2032: 0.077,
  2033: 0.0811,
  2034: 0.0851,
  2035: 0.0892,
  2036: 0.0932,
  2037: 0.0973,
  2038: 0.1013,
  2039: 0.1053,
  2040: 0.1094,
  2041: 0.1134,
  2042: 0.1174,
  2043: 0.1215,
  2044: 0.1255,
  2045: 0.1295,
  2046: 0.1336,
  2047: 0.1376,
  2048: 0.1416,
  2049: 0.1457,
  2050: 0.1497,
  2051: 0.1537,
  2052: 0.1577,
  2053: 0.1618,
  2054: 0.1658,
  2055: 0.1698,
  2056: 0.1739,
  2057: 0.1779,
  2058: 0.1819,
  2059: 0.186,
  2060: 0.19,
  2061: 0.194,
  2062: 0.1981,
  2063: 0.2021,
  2064: 0.2061,
  2065: 0.2102,
  2066: 0.2142,
  2067: 0.2182,
  2068: 0.2223,
  2069: 0.2263,
  2070: 0.2303,
};

// Linear rate extrapolated from 2069–2070 trend for years beyond model coverage.
const EXTRAPOLATION_RATE_M_PER_YEAR = 0.004;
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
