import assert from 'node:assert/strict';
import test from 'node:test';

import { POST } from '@/app/api/voice/respond/route';
import { LOCATIONS } from '@/lib/locations';

const location = LOCATIONS[0];
const sceneState = {
  activeHotspotId: location.defaultHotspotId,
  activeScenarioId: location.scenarios[0].id,
  compareScenarioIds: null,
  riseMeters: 0,
  viewerState: 'ready' as const,
};

test('returns 400 when transcript is missing', async () => {
  const response = await POST(
    new Request('http://localhost/api/voice/respond', {
      method: 'POST',
      body: JSON.stringify({ locationSlug: location.slug, sceneState }),
      headers: { 'Content-Type': 'application/json' },
    }),
  );

  assert.equal(response.status, 400);
});

test('falls back gracefully when model credentials are missing', async () => {
  const originalKey = process.env.NVIDIA_API_KEY;
  delete process.env.NVIDIA_API_KEY;

  try {
    const response = await POST(
      new Request('http://localhost/api/voice/respond', {
        method: 'POST',
        body: JSON.stringify({
          transcript: 'what data is this based on',
          locationSlug: location.slug,
          sceneState,
        }),
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    assert.equal(response.status, 200);
    const payload = (await response.json()) as {
      caption?: string;
      speech?: string;
      status?: string;
    };
    assert.equal(payload.status, 'completed');
    assert.match(String(payload.caption), /Sources:/);
  } finally {
    if (originalKey) {
      process.env.NVIDIA_API_KEY = originalKey;
    }
  }
});
