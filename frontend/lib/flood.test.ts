import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyFloodCalibration,
  buildFloodVolumeFromBounds,
  computeFloodVolumeFromLocalBox,
} from '@/lib/flood';

test('buildFloodVolumeFromBounds derives world bounds and ingress distance', () => {
  const volume = buildFloodVolumeFromBounds({
    min: { x: -2, y: 1, z: -3 },
    max: { x: 6, y: 5, z: 1 },
  });

  assert.deepEqual(volume, {
    startY: 1,
    endY: 5,
    minX: -2,
    maxX: 6,
    minZ: -3,
    maxZ: 1,
    maxEdgeDistance: 2,
  });
});

test('computeFloodVolumeFromLocalBox respects scene rotation when deriving axes', () => {
  const volume = computeFloodVolumeFromLocalBox(
    {
      min: { x: 0, y: 0, z: 0 },
      max: { x: 2, y: 1, z: 4 },
    },
    0,
    Math.PI / 2,
    0,
  );

  assert.equal(volume.startY, 0);
  assert.equal(volume.endY, 1);
  assert.ok(Math.abs(volume.minX - 0) < 1e-9);
  assert.ok(Math.abs(volume.maxX - 4) < 1e-9);
  assert.ok(Math.abs(volume.minZ + 2) < 1e-9);
  assert.ok(Math.abs(volume.maxZ - 0) < 1e-9);
  assert.ok(Math.abs(volume.maxEdgeDistance - 1) < 1e-9);
});

test('applyFloodCalibration lets scene metadata override derived bounds', () => {
  const volume = applyFloodCalibration(
    buildFloodVolumeFromBounds({
      min: { x: -1, y: -2, z: -3 },
      max: { x: 5, y: 8, z: 7 },
    }),
    {
      startY: -1.5,
      endY: 6.5,
      minX: -4,
      maxX: 4,
    },
  );

  assert.equal(volume.startY, -1.5);
  assert.equal(volume.endY, 6.5);
  assert.equal(volume.minX, -4);
  assert.equal(volume.maxX, 4);
  assert.equal(volume.minZ, -3);
  assert.equal(volume.maxZ, 7);
  assert.equal(volume.maxEdgeDistance, 4);
});
