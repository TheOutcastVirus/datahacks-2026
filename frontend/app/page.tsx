import Link from 'next/link';

import { LOCATIONS } from '@/lib/locations';

export default function Home() {
  return (
    <div className="dashboard-shell">
      <header className="masthead">
        <div>
          <div className="eyebrow">Sojs</div>
          <h1 className="dashboard-title">Location Dashboard</h1>
        </div>
        <p className="dashboard-copy">
          Save each render as its own location and open it from a dedicated route.
        </p>
      </header>

      <section className="dashboard-grid" aria-label="Saved locations">
        {LOCATIONS.map((location) => (
          <Link
            key={location.slug}
            href={`/locations/${location.slug}`}
            className="location-card"
          >
            <div className="location-card-topline">
              <span className="location-status">{location.status}</span>
              <span className="location-updated">{location.updatedAt}</span>
            </div>

            <div className="location-card-body">
              <div>
                <h2 className="location-name">{location.name}</h2>
                <p className="location-region">{location.region}</p>
              </div>
              <p className="location-description">{location.description}</p>
            </div>

            <div className="location-card-footer">
              <div className="location-metric">
                <span className="metric-label">Rise</span>
                <strong>{location.scene.rise.toFixed(2)}m</strong>
              </div>
              <div className="location-metric">
                <span className="metric-label">Scenario</span>
                <strong>{location.scene.label}</strong>
              </div>
              <div className="location-open">Open Render</div>
            </div>
          </Link>
        ))}
      </section>
    </div>
  );
}
