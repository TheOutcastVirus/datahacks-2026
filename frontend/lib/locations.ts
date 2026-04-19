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

export type FloodCalibration = {
  startY: number;
  endY: number;
};

export type LocationRecord = {
  slug: string;
  name: string;
  region: string;
  description: string;
  splatUrl: string;
  renderer?: 'auto' | 'ply' | 'splat';
  floodCalibration?: FloodCalibration;
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
        riseMeters: 0.74,
        narration:
          'Mid-century rise begins to pressure the lowest waterfront paths and exposed transport edges.',
        color: '#38bdf8',
      },
      {
        id: 'worst-case',
        label: '2100 Worst Case',
        year: 2100,
        riseMeters: 1.92,
        narration:
          'The highest scenario pushes water well past the current shoreline and into critical waterfront infrastructure.',
        color: '#f97316',
      },
    ],
    defaultHotspotId: 'waterfront',
  },
  {
    slug: 'output-splat',
    name: 'Output Splat',
    region: '',
    description: '',
    splatUrl: '/output.ply',
    renderer: 'splat',
    floodCalibration: {
      startY: -1.5,
      endY: 0.8,
    },
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
        name: 'SLAM output',
        aliases: [
          'slam output',
          'slam',
          'render center',
          'output',
          'splat',
          'scene',
        ],
        description: 'Latest fused point cloud / splat from the SLAM pipeline.',
        cameraPose: {
          position: [-3.5, 2, 5.5],
          target: [0, 0.4, 0],
        },
        explainText: 'Showing the SLAM reconstruction as a Gaussian splat.',
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
        riseMeters: 0.74,
        narration: 'Mid-century rise preview for the output.ply render.',
        color: '#38bdf8',
      },
      {
        id: 'worst-case',
        label: '2100 Worst Case',
        year: 2100,
        riseMeters: 1.92,
        narration: 'Highest-rise preview for the output.ply render.',
        color: '#f97316',
      },
    ],
    defaultHotspotId: 'render-center',
  },
];

export function getLocationBySlug(slug: string) {
  return LOCATIONS.find((location) => location.slug === slug);
}
