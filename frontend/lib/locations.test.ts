import assert from 'node:assert/strict';
import test from 'node:test';

import { LOCATIONS } from '@/lib/locations';

test('all locations define the fields LocationExperience expects', () => {
  for (const location of LOCATIONS) {
    assert.ok(location.hotspots.length > 0, `${location.slug} missing hotspots`);
    assert.ok(location.scenarios.length > 0, `${location.slug} missing scenarios`);
    assert.ok(location.defaultHotspotId, `${location.slug} missing defaultHotspotId`);
  }
});
