import assert from 'node:assert/strict';
import test from 'node:test';

import { getSeaLevel, isExtrapolatedYear, seaLevelCurve } from '@/lib/sea-level-data';

test('clamps years below the 2026 UI baseline', () => {
  assert.equal(getSeaLevel(2025), 0);
  assert.equal(getSeaLevel(2026), 0);
});

test('returns exact values for years present in the exported curve', () => {
  const record2050 = seaLevelCurve.records.find((record) => record.year === 2050);
  assert.ok(record2050);
  assert.equal(getSeaLevel(2050), record2050.riseFrom2026Meters);
});

test('interpolates linearly between adjacent years', () => {
  const left = seaLevelCurve.records.find((record) => record.year === 2040);
  const right = seaLevelCurve.records.find((record) => record.year === 2041);

  assert.ok(left);
  assert.ok(right);

  const midpoint = getSeaLevel(2040.5);
  assert.equal(midpoint, (left.riseFrom2026Meters + right.riseFrom2026Meters) / 2);
});

test('keeps 2100 above the last non-extrapolated year and marks it as extrapolated', () => {
  assert.ok(getSeaLevel(2100) > getSeaLevel(2070));
  assert.equal(isExtrapolatedYear(2100), true);
  assert.equal(isExtrapolatedYear(2050), false);
});
