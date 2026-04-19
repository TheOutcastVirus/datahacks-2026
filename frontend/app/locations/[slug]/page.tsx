import Link from 'next/link';
import { notFound } from 'next/navigation';

import LocationExperience from '@/components/LocationExperience';
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
            SO<span className="logo-accent">GS</span>
          </div>
          <div className="header-sub">Spatiotemporal Oceanographic Growth Simulator</div>
        </div>
        <nav className="header-nav">
          <Link href="/" className="nav-link">
            Dashboard
          </Link>
          {location.region.trim() ? (
            <div className="nav-chip">{location.region}</div>
          ) : null}
        </nav>
      </header>

      <LocationExperience location={location} />
    </div>
  );
}
