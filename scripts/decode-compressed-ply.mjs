#!/usr/bin/env bun
// Decode PlayCanvas splat-transform 0.1.3 compressed PLY -> .splat (32 bytes/gaussian)
// Format:
//   element chunk N    : 18 floats/chunk (min/max xyz, min/max scale xyz, min/max rgb)
//   element vertex M   : 4 uint32/vertex (packed_position, _rotation, _scale, _color)
//   element sh M       : 45 uchar/vertex (ignored in .splat output)
// Chunk size = 256 vertices; vertex i uses chunk floor(i/256).

import { readFileSync, writeFileSync } from 'node:fs';

const INPUT  = process.argv[2] || '3dgs_compressed.ply';
const OUTPUT = process.argv[3] || 'frontend/public/scene.splat';

const buf = readFileSync(INPUT);
const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);

// Find end_header
const headerStr = new TextDecoder('utf-8').decode(buf.subarray(0, Math.min(16384, buf.length)));
const headerEndIdx = headerStr.indexOf('end_header');
if (headerEndIdx < 0) throw new Error('no end_header');
// Skip past 'end_header' + following newline(s)
let dataStart = headerEndIdx + 'end_header'.length;
while (dataStart < buf.length && (buf[dataStart] === 0x0A || buf[dataStart] === 0x0D)) dataStart++;

const nChunks = +headerStr.match(/element chunk (\d+)/)[1];
const nVerts  = +headerStr.match(/element vertex (\d+)/)[1];
const shMatch = headerStr.match(/element sh (\d+)/);
const nSh = shMatch ? +shMatch[1] : 0;
const shCoeffs = (headerStr.match(/property uchar f_rest_/g) || []).length;

console.log(`chunks=${nChunks} vertices=${nVerts} sh=${nSh} sh_coeffs=${shCoeffs}`);

const CHUNK_SIZE = 18 * 4;       // 18 floats
const VERT_SIZE  = 4 * 4;        // 4 uint32
const chunksOffset = dataStart;
const vertsOffset  = chunksOffset + nChunks * CHUNK_SIZE;
const shOffset     = vertsOffset + nVerts * VERT_SIZE;

function chunkAt(i) {
  const o = chunksOffset + i * CHUNK_SIZE;
  return {
    minX: view.getFloat32(o + 0,  true),
    minY: view.getFloat32(o + 4,  true),
    minZ: view.getFloat32(o + 8,  true),
    maxX: view.getFloat32(o + 12, true),
    maxY: view.getFloat32(o + 16, true),
    maxZ: view.getFloat32(o + 20, true),
    minSX: view.getFloat32(o + 24, true),
    minSY: view.getFloat32(o + 28, true),
    minSZ: view.getFloat32(o + 32, true),
    maxSX: view.getFloat32(o + 36, true),
    maxSY: view.getFloat32(o + 40, true),
    maxSZ: view.getFloat32(o + 44, true),
    minR: view.getFloat32(o + 48, true),
    minG: view.getFloat32(o + 52, true),
    minB: view.getFloat32(o + 56, true),
    maxR: view.getFloat32(o + 60, true),
    maxG: view.getFloat32(o + 64, true),
    maxB: view.getFloat32(o + 68, true),
  };
}

// Unpack 11,10,11 -> three normalized floats [0,1]
function unpack111011(v) {
  return [
    ((v >>> 21) & 0x7FF) / 0x7FF,
    ((v >>> 11) & 0x3FF) / 0x3FF,
    (v & 0x7FF) / 0x7FF,
  ];
}

// Largest-component quaternion decode
function unpackRot(v) {
  const NORM = 1.0 / Math.SQRT2;
  const largest = (v >>> 30) & 0x3;
  let a = ((v >>> 20) & 0x3FF) / 0x3FF * 2 * NORM - NORM;
  let b = ((v >>> 10) & 0x3FF) / 0x3FF * 2 * NORM - NORM;
  let c = (v & 0x3FF)          / 0x3FF * 2 * NORM - NORM;
  const m = Math.sqrt(Math.max(0, 1 - a*a - b*b - c*c));
  const q = [0, 0, 0, 0];
  // quaternion order (w,x,y,z) as expected by .splat format
  switch (largest) {
    case 0: q[0] = m; q[1] = a; q[2] = b; q[3] = c; break;
    case 1: q[0] = a; q[1] = m; q[2] = b; q[3] = c; break;
    case 2: q[0] = a; q[1] = b; q[2] = m; q[3] = c; break;
    case 3: q[0] = a; q[1] = b; q[2] = c; q[3] = m; break;
  }
  return q;
}

function sigmoid(x) { return 1 / (1 + Math.exp(-x)); }
const SH_C0 = 0.28209479177387814;

const out = new Uint8Array(nVerts * 32);
const outView = new DataView(out.buffer);

for (let i = 0; i < nVerts; i++) {
  const chunk = chunkAt(Math.floor(i / 256));

  const vo = vertsOffset + i * VERT_SIZE;
  const packedPos = view.getUint32(vo + 0,  true);
  const packedRot = view.getUint32(vo + 4,  true);
  const packedSc  = view.getUint32(vo + 8,  true);
  const packedCol = view.getUint32(vo + 12, true);

  const [px, py, pz] = unpack111011(packedPos);
  const X = chunk.minX + (chunk.maxX - chunk.minX) * px;
  const Y = chunk.minY + (chunk.maxY - chunk.minY) * py;
  const Z = chunk.minZ + (chunk.maxZ - chunk.minZ) * pz;

  const [sx, sy, sz] = unpack111011(packedSc);
  // Decoded values are already in log-scale range [min, max]; exp to world scale
  const SX = Math.exp(chunk.minSX + (chunk.maxSX - chunk.minSX) * sx);
  const SY = Math.exp(chunk.minSY + (chunk.maxSY - chunk.minSY) * sy);
  const SZ = Math.exp(chunk.minSZ + (chunk.maxSZ - chunk.minSZ) * sz);

  // Color: RGBA 8-bit each. RGB is SH DC (pre-sigmoid? no — splat format stores plain RGB 0-255)
  const r = (packedCol >>> 24) & 0xFF;
  const g = (packedCol >>> 16) & 0xFF;
  const b = (packedCol >>>  8) & 0xFF;
  const a = (packedCol >>>  0) & 0xFF;

  const [qw, qx, qy, qz] = unpackRot(packedRot);

  const oo = i * 32;
  outView.setFloat32(oo + 0,  X,  true);
  outView.setFloat32(oo + 4,  Y,  true);
  outView.setFloat32(oo + 8,  Z,  true);
  outView.setFloat32(oo + 12, SX, true);
  outView.setFloat32(oo + 16, SY, true);
  outView.setFloat32(oo + 20, SZ, true);
  out[oo + 24] = r;
  out[oo + 25] = g;
  out[oo + 26] = b;
  out[oo + 27] = a;
  // .splat rotation: 4 bytes, each (q * 128 + 128) clamped 0..255, order (w,x,y,z)
  out[oo + 28] = Math.max(0, Math.min(255, Math.round(qw * 128 + 128)));
  out[oo + 29] = Math.max(0, Math.min(255, Math.round(qx * 128 + 128)));
  out[oo + 30] = Math.max(0, Math.min(255, Math.round(qy * 128 + 128)));
  out[oo + 31] = Math.max(0, Math.min(255, Math.round(qz * 128 + 128)));
}

writeFileSync(OUTPUT, out);
console.log(`wrote ${OUTPUT} (${(out.byteLength / 1e6).toFixed(1)}MB, ${nVerts} gaussians)`);
