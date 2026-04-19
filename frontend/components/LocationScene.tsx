'use client';

import { useState } from 'react';

import SplatViewer from '@/components/SplatViewer';
import { getSeaLevel } from '@/lib/sea-level-data';
import type { LocationRecord } from '@/lib/locations';

const MAX_VISUALIZED_RISE_METERS = 2.0;

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

export default function LocationScene({
  location,
}: {
  location: LocationRecord;
}) {
  const [sliderYear, setSliderYear] = useState(2026);
  const riseMeters = getSeaLevel(sliderYear);
  const floodProgress = clamp(riseMeters / MAX_VISUALIZED_RISE_METERS, 0, 1);
  const riseColor = getRiseColor(floodProgress);

  return (
    <div className="viewport">
      <div className="splat-stage">
        <SplatViewer
          splatUrl={location.splatUrl}
          renderer={location.renderer ?? 'auto'}
          floodProgress={floodProgress}
          floodOverlay={location.floodOverlay}
        />
      </div>

      <div className="stats-panel">
        <div className="stats-label">Sea Level Rise</div>
        <div className="stats-rise" style={{ color: riseColor }}>
          +{riseMeters.toFixed(2)}
          <span className="stats-rise-unit">m</span>
        </div>
        <div className="stats-year">{sliderYear}</div>
        <div className="stats-scenario">
          {location.scene.label}. Drag the slider to raise water through the scan.
        </div>
        <div className="stats-control">
          <label className="stats-control-label" htmlFor="water-level-slider">
            Water Level
          </label>
          <div className="stats-slider-row">
            <input
              id="water-level-slider"
              className="stats-slider"
              type="range"
              min={2026}
              max={2100}
              step={1}
              value={sliderYear}
              onChange={event => {
                setSliderYear(Number.parseInt(event.currentTarget.value, 10));
              }}
              aria-label="Year"
            />
            <div className="stats-slider-value">{Math.round(floodProgress * 100)}%</div>
          </div>
          <div className="stats-slider-scale">
            <span>2026</span>
            <span>2100</span>
          </div>
        </div>
      </div>

      <div className="attr-panel">
        <div className="attr-title">Location</div>
        <div className="attr-item attr-item-strong">{location.name}</div>
        {location.description.trim() ? (
          <div className="attr-item">{location.description}</div>
        ) : null}
        <div className="attr-title attr-title-spaced">Data Sources</div>
        {location.sources.map((source) => (
          <div key={source} className="attr-item">
            {source}
          </div>
        ))}
      </div>
    </div>
  );
}
