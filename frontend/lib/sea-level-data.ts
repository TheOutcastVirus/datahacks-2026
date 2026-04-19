import curve from '@/data/sea-level/california-demo-default.json';

export type SeaLevelCurveRecord = {
  year: number;
  absoluteMslMeters: number;
  riseFrom2000Meters: number;
  riseFrom2026Meters: number;
  isExtrapolated: boolean;
};

export type SeaLevelCurveFile = {
  curveId: 'california-demo-default';
  projectName: 'SAWJESS';
  sourceLabel: string;
  sourceRegionLabel: string;
  sourceStationId: string;
  baselineYearScientific: 2000;
  baselineYearUi: 2026;
  aggregation: 'calendar_year_mean';
  extrapolationMethod: 'ols_last_10_years';
  records: SeaLevelCurveRecord[];
};

const seaLevelCurve = curve as SeaLevelCurveFile;
const curveRecords = seaLevelCurve.records;
const curveByYear = new Map<number, SeaLevelCurveRecord>(
  curveRecords.map((record) => [record.year, record]),
);
const firstRecord = curveRecords[0];
const lastRecord = curveRecords[curveRecords.length - 1];

function interpolate(left: SeaLevelCurveRecord, right: SeaLevelCurveRecord, year: number) {
  const span = right.year - left.year;
  if (span <= 0) {
    return left.riseFrom2026Meters;
  }

  const progress = (year - left.year) / span;
  return left.riseFrom2026Meters + (right.riseFrom2026Meters - left.riseFrom2026Meters) * progress;
}

export function getSeaLevel(year: number): number {
  if (year <= seaLevelCurve.baselineYearUi) {
    return 0;
  }

  if (year >= lastRecord.year) {
    return lastRecord.riseFrom2026Meters;
  }

  const exact = curveByYear.get(year);
  if (exact) {
    return exact.riseFrom2026Meters;
  }

  const leftYear = Math.floor(year);
  const rightYear = Math.ceil(year);
  const left = curveByYear.get(leftYear);
  const right = curveByYear.get(rightYear);

  if (!left && !right) {
    return 0;
  }

  if (!left) {
    return right!.riseFrom2026Meters;
  }

  if (!right) {
    return left.riseFrom2026Meters;
  }

  return interpolate(left, right, year);
}

export function getSeaLevelCurveId() {
  return seaLevelCurve.curveId;
}

export function getSeaLevelSourceLabel() {
  return `${seaLevelCurve.sourceLabel} (${seaLevelCurve.sourceRegionLabel}, station ${seaLevelCurve.sourceStationId})`;
}

export function isExtrapolatedYear(year: number) {
  if (year <= firstRecord.year) {
    return false;
  }

  if (year >= lastRecord.year) {
    return lastRecord.isExtrapolated;
  }

  const left = curveByYear.get(Math.floor(year));
  const right = curveByYear.get(Math.ceil(year));
  return Boolean(left?.isExtrapolated || right?.isExtrapolated);
}

export { seaLevelCurve };
