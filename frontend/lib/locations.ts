import type { CameraPose } from '@/lib/viewer-types';

export type SceneHotspot = {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  cameraPose: CameraPose;
  explainText: string;
};

export type ScenarioRecord = {
  id: string;
  label: string;
  year: number;
  riseMeters: number;
  narration: string;
  color: string;
};

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
  hotspots: SceneHotspot[];
  scenarios: ScenarioRecord[];
  defaultHotspotId: string;
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
    hotspots: [
      {
        id: 'waterfront',
        name: 'Waterfront',
        aliases: ['waterfront', 'shoreline', 'main waterfront'],
        description: 'The main public edge where the boardwalk meets the shoreline.',
        cameraPose: {
          position: [-4.4, 2.25, 6.2],
          target: [-0.2, 0.45, 0.25],
        },
        explainText:
          'Showing the waterfront. This low public edge is where rising water becomes easiest to understand at a glance.',
      },
      {
        id: 'pier',
        name: 'Pier',
        aliases: ['pier', 'dock', 'boardwalk'],
        description: 'A long exposed edge that gives a clear view of low-lying flood exposure.',
        cameraPose: {
          position: [2.8, 1.7, 5.8],
          target: [0.85, 0.25, -0.35],
        },
        explainText:
          'Showing the pier. This edge floods earlier because it sits directly on the open shoreline with less elevation buffer.',
      },
      {
        id: 'ferry-terminal',
        name: 'Ferry Terminal',
        aliases: ['ferry terminal', 'terminal', 'ferry'],
        description: 'An infrastructure viewpoint that makes transport risk easier to discuss.',
        cameraPose: {
          position: [5.35, 2.4, 2.5],
          target: [1.25, 0.65, 0.2],
        },
        explainText:
          'Showing the ferry terminal. Transport infrastructure here becomes more vulnerable as sea rise pushes water into the terminal edge.',
      },
      {
        id: 'seawall',
        name: 'Seawall',
        aliases: ['seawall', 'sea wall', 'wall'],
        description: 'A close look at the hardened edge that separates public space from the waterline.',
        cameraPose: {
          position: [-1.6, 1.3, 3.6],
          target: [-0.05, 0.15, -0.25],
        },
        explainText:
          'Showing the seawall. This boundary helps frame where water first overtops the protected edge in higher scenarios.',
      },
    ],
    scenarios: [
      {
        id: 'baseline',
        label: 'Baseline',
        year: 2026,
        riseMeters: 0,
        narration:
          'Baseline view with present-day shoreline conditions and no added sea-level rise.',
        color: '#00d4b4',
      },
      {
        id: 'mid-century',
        label: '2050 Outlook',
        year: 2050,
        riseMeters: 0.15,
        narration:
          'Mid-century rise begins to pressure the lowest waterfront paths and exposed transport edges.',
        color: '#38bdf8',
      },
      {
        id: 'worst-case',
        label: '2100 Projection',
        year: 2100,
        riseMeters: 0.35,
        narration:
          'End-of-century projection based on observed tidal trends extrapolated from NOAA station data.',
        color: '#f97316',
      },
    ],
    defaultHotspotId: 'waterfront',
  },
  {
    slug: 'annaberg',
    name: 'Annaberg Sugar Plantation',
    region: 'St. John, U.S. Virgin Islands',
    description:
      'Aerial photogrammetry capture of the Annaberg Sugar Plantation ruins. Gaussian splat render from the latest output.ply export.',
    splatUrl: '/annaberg_output.ply',
    renderer: 'splat',
    status: 'Render Ready',
    updatedAt: 'April 19, 2026',
    scene: {
      year: 2026,
      rise: 0,
      label: 'Output',
      color: '#f59e0b',
    },
    sources: ['output.ply export', 'Gaussian splat renderer'],
    hotspots: [
      {
        id: 'render-center',
        name: 'Render Center',
        aliases: ['render center', 'output', 'splat', 'scene', 'plantation'],
        description: 'The center view for the Annaberg Sugar Plantation splat render.',
        cameraPose: {
          position: [-1.0, 0.5, 1.2],
          target: [0, 0, 0],
        },
        explainText: 'Showing the Annaberg Sugar Plantation ruins from the aerial Gaussian splat render.',
      },
    ],
    scenarios: [
      {
        id: 'baseline',
        label: 'Baseline',
        year: 2026,
        riseMeters: 0,
        narration: 'Baseline render capture of Annaberg Sugar Plantation with no added sea-level rise.',
        color: '#f59e0b',
      },
      {
        id: 'mid-century',
        label: '2050 Outlook',
        year: 2050,
        riseMeters: 0.74,
        narration: 'Mid-century rise preview for Annaberg.',
        color: '#38bdf8',
      },
      {
        id: 'worst-case',
        label: '2100 Worst Case',
        year: 2100,
        riseMeters: 1.92,
        narration: 'Highest-rise preview for Annaberg.',
        color: '#f97316',
      },
    ],
    defaultHotspotId: 'render-center',
  },
  {
    slug: 'maine',
    name: 'Maine',
    region: 'Local render capture',
    description:
      'Gaussian splat render from the latest output.ply export. Use this row to open the corrected splat renderer directly.',
    splatUrl: '/maine_output.ply',
    renderer: 'splat',
    status: 'Render Ready',
    updatedAt: 'April 18, 2026',
    scene: {
      year: 2026,
      rise: 0,
      label: 'Output',
      color: '#7dd3fc',
    },
    sources: ['output.ply export', 'Gaussian splat renderer'],
    hotspots: [
      {
        id: 'render-center',
        name: 'Render Center',
        aliases: ['render center', 'output', 'splat', 'scene'],
        description: 'The center view for the latest output.ply export.',
        cameraPose: {
          position: [-3.5, 2, 5.5],
          target: [0, 0.4, 0],
        },
        explainText: 'Showing the render center for the latest output.ply export.',
      },
    ],
    scenarios: [
      {
        id: 'baseline',
        label: 'Baseline',
        year: 2026,
        riseMeters: 0,
        narration: 'Baseline render capture from output.ply with no added sea-level rise.',
        color: '#7dd3fc',
      },
      {
        id: 'mid-century',
        label: '2050 Outlook',
        year: 2050,
        riseMeters: 0.15,
        narration: 'Mid-century rise preview for the output.ply render.',
        color: '#38bdf8',
      },
      {
        id: 'worst-case',
        label: '2100 Projection',
        year: 2100,
        riseMeters: 0.35,
        narration: 'End-of-century projection based on observed tidal trends extrapolated from NOAA station data.',
        color: '#f97316',
      },
    ],
    defaultHotspotId: 'render-center',
  },
  {
    slug: 'uk-coastline',
    name: 'UK Coastline',
    region: 'United Kingdom',
    description:
      'Aerial drone capture of the UK coastline. Gaussian splat render from photogrammetry output.',
    splatUrl: '/uk_output.ply',
    renderer: 'splat',
    status: 'Render Ready',
    updatedAt: 'April 19, 2026',
    scene: {
      year: 2026,
      rise: 0,
      label: 'Baseline',
      color: '#60a5fa',
    },
    sources: ['Aerial drone footage', 'Gaussian splat renderer'],
    hotspots: [
      {
        id: 'render-center',
        name: 'Coastline View',
        aliases: ['render center', 'coastline', 'coast', 'cliff', 'scene'],
        description: 'Aerial view of the UK coastline captured by drone.',
        cameraPose: {
          position: [0, 0, 1.5],
          target: [0, 0, 0],
        },
        explainText: 'Showing the UK coastline from the aerial Gaussian splat render.',
      },
    ],
    scenarios: [
      {
        id: 'baseline',
        label: 'Baseline',
        year: 2026,
        riseMeters: 0,
        narration: 'Baseline aerial capture of the UK coastline with no added sea-level rise.',
        color: '#60a5fa',
      },
      {
        id: 'mid-century',
        label: '2050 Outlook',
        year: 2050,
        riseMeters: 0.85,
        narration: 'Mid-century sea level rise begins to affect low-lying coastal areas.',
        color: '#38bdf8',
      },
      {
        id: 'worst-case',
        label: '2100 Projection',
        year: 2100,
        riseMeters: 2.0,
        narration: 'End-of-century projection showing significant coastal inundation risk.',
        color: '#f97316',
      },
    ],
    defaultHotspotId: 'render-center',
  },
];

export function getLocationBySlug(slug: string) {
  return LOCATIONS.find((location) => location.slug === slug);
}
