import Link from 'next/link';
import { notFound } from 'next/navigation';

import SplatViewer from '@/components/SplatViewer';
import { LOCATIONS, getLocationBySlug } from '@/lib/locations';

export function generateStaticParams() {
  return LOCATIONS.map((location) => ({ slug: location.slug }));
}

export default async function LocationPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const location = getLocationBySlug(slug);

  if (!location) {
    notFound();
  }

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <div className="logo">
            SO<span className="logo-accent">JS</span>
          </div>
          <div className="header-sub">Location Render</div>
        </div>
        <nav className="header-nav">
          <Link href="/" className="nav-link">
            Dashboard
          </Link>
          <div className="nav-chip">{location.region}</div>
        </nav>
      </header>

      <div className="viewport">
        <div className="splat-stage">
          <SplatViewer
            splatUrl={location.splatUrl}
            renderer={location.renderer ?? 'auto'}
          />
        </div>

        <div className="stats-panel">
          <div className="stats-label">Sea Level Rise</div>
          <div className="stats-rise" style={{ color: location.scene.color }}>
            +{location.scene.rise.toFixed(2)}
            <span className="stats-rise-unit">m</span>
          </div>
          <div className="stats-year">{location.scene.year}</div>
          <div className="stats-scenario">{location.scene.label}</div>
        </div>

        <div className="attr-panel">
          <div className="attr-title">Location</div>
          <div className="attr-item attr-item-strong">{location.name}</div>
          <div className="attr-item">{location.description}</div>
          <div className="attr-title attr-title-spaced">Data Sources</div>
          {location.sources.map((source) => (
            <div key={source} className="attr-item">
              {source}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
