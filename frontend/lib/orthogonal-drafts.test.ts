import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createLocationRecordSnippet,
  normalizeGeneratedLocationDraft,
} from '@/lib/orthogonal-drafts';

test('normalizeGeneratedLocationDraft fills required Sojs defaults', () => {
  const draft = normalizeGeneratedLocationDraft(
    {
      name: 'Alki Beach',
      hotspots: [{ name: 'Boardwalk', aliases: ['walkway'] }],
      scenarios: [{ label: '2050 Draft', year: 2050, riseMeters: 0.64, color: '#38bdf8' }],
    },
    'alki beach',
  );

  assert.equal(draft.slug, 'alki-beach');
  assert.ok(draft.hotspots.length > 0);
  assert.ok(draft.scenarios.length >= 1);
  assert.equal(draft.defaultHotspotId, draft.hotspots[0]?.id);
});

test('createLocationRecordSnippet emits a copy-pasteable LocationRecord block', () => {
  const draft = normalizeGeneratedLocationDraft(
    {
      name: 'Alki Beach',
      region: 'Seattle, Washington',
      sources: ['NOAA sea level trends'],
    },
    'alki beach',
  );
  const snippet = createLocationRecordSnippet(draft);

  assert.match(snippet, /slug: 'alki-beach'/);
  assert.match(snippet, /cameraPose/);
  assert.match(snippet, /defaultHotspotId/);
});
