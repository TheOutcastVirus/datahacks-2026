'use client';

import { useState } from 'react';

import SplatViewer from '@/components/SplatViewer';

const MAX_VISUALIZED_RISE_METERS = 2.0;
const BASE_SCENE = {
  mode: 'Manual Control',
  rise: 0,
  label: 'Drag the slider to raise water through the scan.',
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function mixChannel(start: number, end: number, amount: number) {
  return Math.round(start + (end - start) * amount);
}

function getRiseColor(progress: number) {
  const start = { r: 0x00, g: 0xd4, b: 0xb4 };
  const end = { r: 0x16, g: 0x7d, b: 0x96 };
  const amount = clamp(progress, 0, 1);

  const r = mixChannel(start.r, end.r, amount);
  const g = mixChannel(start.g, end.g, amount);
  const b = mixChannel(start.b, end.b, amount);

  return `rgb(${r}, ${g}, ${b})`;
}

export default function Home() {
  const [riseMeters, setRiseMeters] = useState(BASE_SCENE.rise);
  const floodProgress = clamp(riseMeters / MAX_VISUALIZED_RISE_METERS, 0, 1);
  const scene = {
    ...BASE_SCENE,
    rise: riseMeters,
    color: getRiseColor(floodProgress),
  };

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="logo">
          SO<span className="logo-accent">JS</span>
        </div>
        <div className="header-sub">Sea Level Rise Simulation</div>
        <nav className="header-nav">
          <button className="nav-btn active">3D VIEW</button>
          <button className="nav-btn">DATA</button>
          <button className="nav-btn">ABOUT</button>
        </nav>
      </header>

        {/* Viewport: centered stage (not full-bleed) = fewer pixels, smoother perf */}
      <div className="viewport">
        <div className="splat-stage">
          <SplatViewer
            splatUrl="/Cabbage-mvs_1012_04.ply"
            renderer="auto"
            floodProgress={floodProgress}
          />
        </div>

        {/* Stats */}
        <div className="stats-panel">
          <div className="stats-label">Sea Level Rise</div>
          <div className="stats-rise" style={{ color: scene.color }}>
            +{scene.rise.toFixed(2)}
            <span className="stats-rise-unit">m</span>
          </div>
          <div className="stats-year">{scene.mode}</div>
          <div className="stats-scenario">{scene.label}</div>
          <div className="stats-control">
            <label className="stats-control-label" htmlFor="water-level-slider">
              Water Level
            </label>
            <div className="stats-slider-row">
              <input
                id="water-level-slider"
                className="stats-slider"
                type="range"
                min={0}
                max={MAX_VISUALIZED_RISE_METERS}
                step={0.01}
                value={riseMeters}
                onChange={event => {
                  setRiseMeters(Number.parseFloat(event.currentTarget.value));
                }}
                aria-label="Water level"
              />
              <div className="stats-slider-value">{Math.round(floodProgress * 100)}%</div>
            </div>
            <div className="stats-slider-scale">
              <span>Dry</span>
              <span>Flooded</span>
            </div>
          </div>
        </div>

        {/* Attribution */}
        <div className="attr-panel">
          <div className="attr-title">Data Sources</div>
          {['NASA Ice Cap Metrics', 'Gulf of Mexico Spray Data', 'NOAA Heat Index'].map(s => (
            <div key={s} className="attr-item">{s}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
