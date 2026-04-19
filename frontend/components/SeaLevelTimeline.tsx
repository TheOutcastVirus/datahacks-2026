'use client';

import { useMemo } from 'react';
import { getSeaLevel } from '@/lib/sea-level-data';

type Props = {
  sliderYear: number;
  riseMeters: number;
  onYearChange: (year: number, riseMeters: number) => void;
  onHide: () => void;
};

type Phase = {
  range: [number, number];
  headline: string;
  description: string;
  impacts: string[];
  color: string;
};

const PHASES: Phase[] = [
  {
    range: [2026, 2035],
    headline: 'Early Warning Signs',
    description: 'Thermal expansion and accelerating ice melt begin raising sea levels. Changes are subtle but measurable at tide gauges worldwide.',
    impacts: ['King tides flood streets more often', 'Coastal insurance premiums rising', 'Storm surge damage increases'],
    color: '#00d4b4',
  },
  {
    range: [2035, 2055],
    headline: 'Coastal Stress',
    description: 'Sea level rise accelerates as ice sheet dynamics become harder to reverse. Infrastructure built for the 20th century begins to strain.',
    impacts: ['Storm surge damage doubles', 'Coastal wetlands losing ground fast', 'Billions in property at elevated risk'],
    color: '#fbbf24',
  },
  {
    range: [2055, 2080],
    headline: 'Managed Retreat Begins',
    description: 'Coastal communities face a stark choice: protect, adapt, or relocate. The economics of living near the ocean fundamentally shift.',
    impacts: ['Major ports require costly redesign', 'Seawall construction accelerates globally', 'Millions become climate-displaced'],
    color: '#f97316',
  },
  {
    range: [2080, 2101],
    headline: 'Permanent Transformation',
    description: 'Coastlines look fundamentally different. Decisions made in the 2020s–2040s determine which cities survive and which are lost to the sea.',
    impacts: ['Permanent inundation of low-lying areas', 'Global food supply disrupted', 'Coastal cultures and ecosystems lost'],
    color: '#ef4444',
  },
];

const MILESTONES = [
  { year: 2035, label: 'Frequent flooding' },
  { year: 2055, label: 'Infrastructure stress' },
  { year: 2080, label: 'Relocation phase' },
];

function getPhase(year: number): Phase {
  return PHASES.find(p => year >= p.range[0] && year < p.range[1]) ?? PHASES[PHASES.length - 1];
}

export default function SeaLevelTimeline({ sliderYear, riseMeters, onYearChange, onHide }: Props) {
  const phase = useMemo(() => getPhase(sliderYear), [sliderYear]);
  const feet = (riseMeters * 3.28084).toFixed(2);

  return (
    <div style={{
      position: 'absolute',
      bottom: 24,
      right: 16,
      zIndex: 30,
      width: 460,
      background: 'rgba(2, 8, 16, 0.95)',
      border: `1px solid ${phase.color}55`,
      backdropFilter: 'blur(16px)',
      fontFamily: 'var(--font-body)',
      boxShadow: '0 0 0 1px rgba(0,0,0,0.6), 0 8px 32px rgba(0,0,0,0.6)',
      transition: 'border-color 0.6s ease',
    }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px 8px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', color: phase.color, transition: 'color 0.6s ease' }}>
          Sea Level Rise
        </span>
        <button type="button" onClick={onHide} aria-label="Hide" style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.3)', fontSize: 16, cursor: 'pointer', padding: 0, lineHeight: 1 }}>&#x00d7;</button>
      </div>

      {/* Year + Rise */}
      <div style={{ padding: '16px 18px 0', display: 'flex', alignItems: 'flex-end', gap: 20 }}>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 68, fontWeight: 300, lineHeight: 1, color: phase.color, transition: 'color 0.6s ease' }}>
            {sliderYear}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.25)', letterSpacing: '0.15em', marginTop: 4 }}>YEAR</div>
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 34, fontWeight: 300, color: '#d6f0f8' }}>
            +{riseMeters.toFixed(2)}<span style={{ fontSize: 18, opacity: 0.45, marginLeft: 5 }}>m</span>
          </div>
          <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.28)', marginTop: 3 }}>{feet} ft</div>
        </div>
      </div>

      {/* Slider + milestones */}
      <div style={{ padding: '10px 18px 4px' }}>
        <input
          type="range"
          min={2026}
          max={2126}
          step={1}
          value={sliderYear}
          onChange={e => {
            const year = Number.parseInt(e.target.value, 10);
            void getSeaLevel(year).then((rise) => {
              onYearChange(year, rise);
            });
          }}
          className="stats-slider"
          style={{ width: '100%', accentColor: phase.color }}
        />
        <div style={{ position: 'relative', height: 22, marginTop: 2 }}>
          {MILESTONES.map(m => {
            const pos = ((m.year - 2026) / (2126 - 2026)) * 100;
            return (
              <div key={m.year} style={{ position: 'absolute', left: `${pos}%`, transform: 'translateX(-50%)', textAlign: 'center' }}>
                <div style={{ width: 1, height: 4, background: 'rgba(255,255,255,0.18)', margin: '0 auto 2px' }} />
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'rgba(255,255,255,0.22)', whiteSpace: 'nowrap', letterSpacing: '0.08em' }}>{m.year}</div>
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 8, color: 'rgba(255,255,255,0.18)', marginTop: 2 }}>
          <span>2026</span><span>2126</span>
        </div>
      </div>

      {/* Phase info */}
      <div style={{ margin: '8px 18px 18px', padding: '12px 14px', background: 'rgba(255,255,255,0.03)', borderLeft: `2px solid ${phase.color}88`, transition: 'border-color 0.6s ease' }}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600, color: '#d6f0f8', marginBottom: 8, letterSpacing: '0.01em' }}>
          {phase.headline}
        </div>
        <div style={{ fontSize: 14, color: 'rgba(214,240,248,0.6)', lineHeight: 1.7, marginBottom: 10 }}>
          {phase.description}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {phase.impacts.map((impact) => (
            <div key={impact} style={{ fontSize: 13, color: 'rgba(214,240,248,0.45)', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <span style={{ color: phase.color, opacity: 0.7, flexShrink: 0 }}>›</span>
              {impact}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
