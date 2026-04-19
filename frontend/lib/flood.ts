import { Euler, Matrix4, Vector3 } from 'three';

export type FloodCalibration = {
  startY: number;
  endY: number;
};

export type Bounds3D = {
  min: { x: number; y: number; z: number };
  max: { x: number; y: number; z: number };
};

export type FloodVolume = {
  startY: number;
  endY: number;
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  maxEdgeDistance: number;
};

export function lerp(start: number, end: number, amount: number) {
  return start + (end - start) * amount;
}

export function buildFloodVolumeFromBounds(bounds: Bounds3D): FloodVolume {
  const width = Math.max(bounds.max.x - bounds.min.x, 0);
  const depth = Math.max(bounds.max.z - bounds.min.z, 0);

  return {
    startY: bounds.min.y,
    endY: bounds.max.y,
    minX: bounds.min.x,
    maxX: bounds.max.x,
    minZ: bounds.min.z,
    maxZ: bounds.max.z,
    maxEdgeDistance: Math.max(Math.min(width, depth) * 0.5, 0.001),
  };
}

export function applyFloodCalibration(
  volume: FloodVolume,
  calibration?: FloodCalibration,
): FloodVolume {
  const next = {
    ...volume,
    ...(calibration ?? {}),
  };

  const width = Math.max(next.maxX - next.minX, 0);
  const depth = Math.max(next.maxZ - next.minZ, 0);

  return {
    ...next,
    maxEdgeDistance: Math.max(Math.min(width, depth) * 0.5, 0.001),
  };
}

export function computeFloodVolumeFromLocalBox(
  localBox: Bounds3D,
  rx: number,
  ry: number,
  rz: number,
  calibration?: FloodCalibration,
): FloodVolume {
  const rotationMatrix = new Matrix4().makeRotationFromEuler(
    new Euler(rx, ry, rz, 'XYZ'),
  );

  const xs = [localBox.min.x, localBox.max.x];
  const ys = [localBox.min.y, localBox.max.y];
  const zs = [localBox.min.z, localBox.max.z];

  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;

  for (const x of xs) {
    for (const y of ys) {
      for (const z of zs) {
        const point = new Vector3(x, y, z).applyMatrix4(rotationMatrix);
        minX = Math.min(minX, point.x);
        minY = Math.min(minY, point.y);
        minZ = Math.min(minZ, point.z);
        maxX = Math.max(maxX, point.x);
        maxY = Math.max(maxY, point.y);
        maxZ = Math.max(maxZ, point.z);
      }
    }
  }

  return applyFloodCalibration(
    buildFloodVolumeFromBounds({
      min: { x: minX, y: minY, z: minZ },
      max: { x: maxX, y: maxY, z: maxZ },
    }),
    calibration,
  );
}

export function buildEulerRotationMatrices(
  rx: number,
  ry: number,
  rz: number,
): {
  rotationMatrix: number[];
  inverseRotationMatrix: number[];
} {
  const rotationMatrix = new Matrix4().makeRotationFromEuler(
    new Euler(rx, ry, rz, 'XYZ'),
  );
  const inverseRotationMatrix = rotationMatrix.clone().invert();

  return {
    rotationMatrix: rotationMatrix.toArray(),
    inverseRotationMatrix: inverseRotationMatrix.toArray(),
  };
}
