'use client';

import SplatViewer from '@/components/SplatViewer';

const SCENE = {
  year: 2025,
  rise: 0,
  label: 'Current',
  color: '#00d4b4',
};

export default function Home() {
  const scene = SCENE;

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
          <SplatViewer splatUrl="/Cabbage-mvs_1012_04.ply" />
        </div>

        {/* Stats */}
        <div className="stats-panel">
          <div className="stats-label">Sea Level Rise</div>
          <div className="stats-rise" style={{ color: scene.color }}>
            +{scene.rise.toFixed(2)}
            <span className="stats-rise-unit">m</span>
          </div>
          <div className="stats-year">{scene.year}</div>
          <div className="stats-scenario">{scene.label}</div>
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
