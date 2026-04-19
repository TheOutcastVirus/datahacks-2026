import assert from 'node:assert/strict';
import test from 'node:test';

import { LOCATIONS } from '@/lib/locations';
import { getSeaLevel, getSeaLevelCurveId } from '@/lib/sea-level-data';

test('all locations define the fields LocationExperience expects', () => {
  for (const location of LOCATIONS) {
    assert.ok(location.hotspots.length > 0, `${location.slug} missing hotspots`);
    assert.ok(location.scenarios.length > 0, `${location.slug} missing scenarios`);
    assert.ok(location.defaultHotspotId, `${location.slug} missing defaultHotspotId`);
    assert.equal(location.seaLevelCurveId, getSeaLevelCurveId());
  }
});

test('all scenario rises are derived from the shared sea-level curve', () => {
  for (const location of LOCATIONS) {
    const baseline = location.scenarios.find((scenario) => scenario.id === 'baseline');
    const midCentury = location.scenarios.find((scenario) => scenario.id === 'mid-century');
    const worstCase = location.scenarios.find((scenario) => scenario.id === 'worst-case');

    assert.ok(baseline, `${location.slug} missing baseline scenario`);
    assert.ok(midCentury, `${location.slug} missing mid-century scenario`);
    assert.ok(worstCase, `${location.slug} missing worst-case scenario`);

    assert.equal(baseline.riseMeters, getSeaLevel(2026));
    assert.equal(midCentury.riseMeters, getSeaLevel(2050));
    assert.equal(worstCase.riseMeters, getSeaLevel(2100));
  }
});
