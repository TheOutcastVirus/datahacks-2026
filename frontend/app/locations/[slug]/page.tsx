import Link from 'next/link';
import { notFound } from 'next/navigation';

import LocationScene from '@/components/LocationScene';
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

      <LocationScene location={location} />
    </div>
  );
}
