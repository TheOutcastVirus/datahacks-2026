export type LocationRecord = {
  slug: string;
  name: string;
  region: string;
  description: string;
  splatUrl: string;
  renderer?: 'auto' | 'ply' | 'splat';
  status: string;
  updatedAt: string;
  scene: {
    year: number;
    rise: number;
    label: string;
    color: string;
  };
  sources: string[];
};

export const LOCATIONS: LocationRecord[] = [
  {
    slug: 'seattle-waterfront',
    name: 'Seattle Waterfront',
    region: 'Seattle, Washington',
    description:
      'Baseline capture for the Seattle waterfront render. Use this route as the entry point for future location-specific scenes.',
    splatUrl: '/Cabbage-mvs_1012_04.ply',
    renderer: 'ply',
    status: 'Render Ready',
    updatedAt: 'April 18, 2026',
    scene: {
      year: 2026,
      rise: 0,
      label: 'Baseline',
      color: '#00d4b4',
    },
    sources: ['NASA Ice Cap Metrics', 'NOAA Tidal Records', 'Local shoreline survey'],
  },
];

export function getLocationBySlug(slug: string) {
  return LOCATIONS.find((location) => location.slug === slug);
}
