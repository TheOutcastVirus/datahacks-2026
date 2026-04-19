import {
  getSeaLevel,
  getSeaLevelCurveId,
  getSeaLevelSourceLabel,
} from '@/lib/sea-level-data';
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
  minX?: number;
  maxX?: number;
  minZ?: number;
  maxZ?: number;
};

export type FloodOverlayPoint = {
  x: number;
  z: number;
};

export type FloodOverlayRegion = {
  id: string;
  label: string;
  polygon: FloodOverlayPoint[];
  minProgress?: number;
  maxProgress?: number;
};

export type FloodOverlay = {
  regions: FloodOverlayRegion[];
};

export type LocationRecord = {
  slug: string;
  name: string;
  region: string;
  description: string;
  seaLevelCurveId: string;
  splatUrl: string;
  renderer?: 'auto' | 'ply' | 'splat';
  floodCalibration?: FloodCalibration;
  floodOverlay?: FloodOverlay;
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

const DEMO_CURVE_ID = getSeaLevelCurveId();

function buildScenario(
  id: ScenarioRecord['id'],
  label: string,
  year: number,
  narration: string,
  color: string,
): ScenarioRecord {
  return {
    id,
    label,
    year,
    riseMeters: getSeaLevel(year),
    narration,
    color,
  };
}

function buildSources(localSource: string): string[] {
  return [
    getSeaLevelSourceLabel(),
    'California-derived demo curve applied uniformly across SAWJESS scenes for the hackathon build.',
    localSource,
  ];
}

export const LOCATIONS: LocationRecord[] = [
  {
    slug: 'seattle-waterfront',
    name: 'Seattle Waterfront',
    region: 'Seattle, Washington',
    description:
      'Baseline capture for the Seattle waterfront render. Use this route as the entry point for future location-specific scenes.',
    seaLevelCurveId: DEMO_CURVE_ID,
    splatUrl: '/Cabbage-mvs_1012_04.ply',
    renderer: 'ply',
    floodOverlay: {
      regions: [
        {
          id: 'shoreline-band',
          label: 'Shoreline band',
          minProgress: 0.08,
          maxProgress: 0.72,
          polygon: [
            { x: 0.08, z: 0.18 },
            { x: 0.22, z: 0.12 },
            { x: 0.58, z: 0.10 },
            { x: 0.92, z: 0.15 },
            { x: 0.95, z: 0.30 },
            { x: 0.70, z: 0.42 },
            { x: 0.34, z: 0.46 },
            { x: 0.12, z: 0.36 },
          ],
        },
        {
          id: 'promenade-pocket',
          label: 'Promenade pocket',
          minProgress: 0.34,
          maxProgress: 0.9,
          polygon: [
            { x: 0.24, z: 0.34 },
            { x: 0.46, z: 0.28 },
            { x: 0.60, z: 0.35 },
            { x: 0.54, z: 0.52 },
            { x: 0.30, z: 0.56 },
            { x: 0.18, z: 0.46 },
          ],
        },
      ],
    },
    status: 'Render Ready',
    updatedAt: 'April 18, 2026',
    scene: {
      year: 2026,
      rise: getSeaLevel(2026),
      label: 'Baseline',
      color: '#00d4b4',
    },
    sources: buildSources('Seattle shoreline render, flood overlay, and hotspot calibration.'),
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
      buildScenario(
        'baseline',
        'Baseline',
        2026,
        'Baseline shoreline conditions with the 2026 California demo curve applied as zero added water-level offset.',
        '#00d4b4',
      ),
      buildScenario(
        'mid-century',
        '2050 Outlook',
        2050,
        'The shared California demo curve adds a modest 2050 offset to the Seattle scene for comparison.',
        '#38bdf8',
      ),
      buildScenario(
        'worst-case',
        '2100 Projection',
        2100,
        'The 2100 view uses the extrapolated California demo curve as a global vertical water-level signal.',
        '#f97316',
      ),
    ],
    defaultHotspotId: 'waterfront',
  },
  {
    slug: 'maine',
    name: 'Maine',
    region: 'Maine',
    description:
      'Gaussian splat render for Maine. Use this route to open the corrected renderer directly.',
    seaLevelCurveId: DEMO_CURVE_ID,
    splatUrl: '/maine_output.ply',
    renderer: 'splat',
    floodCalibration: {
      startY: -1.5,
      endY: 0.8,
    },
    status: 'Render Ready',
    updatedAt: 'April 18, 2026',
    scene: {
      year: 2026,
      rise: getSeaLevel(2026),
      label: 'Baseline',
      color: '#7dd3fc',
    },
    sources: buildSources('Maine Gaussian splat render and local flood calibration.'),
    hotspots: [
      {
        id: 'render-center',
        name: 'Render Center',
        aliases: ['render center', 'output', 'splat', 'scene', 'slam output', 'slam'],
        description:
          'Opening view matches training camera frame_0001 from the Maine export.',
        cameraPose: {
          position: [-3.5, 2, 5.5],
          target: [0, 0.4, 0],
        },
        explainText:
          'Default splat view uses the first training-camera pose from the Maine export.',
      },
    ],
    scenarios: [
      buildScenario(
        'baseline',
        'Baseline',
        2026,
        'Baseline Maine render with the shared California demo curve pinned to the 2026 zero-offset year.',
        '#7dd3fc',
      ),
      buildScenario(
        'mid-century',
        '2050 Outlook',
        2050,
        'The Maine scene reuses the same California-derived 2050 demo curve for a consistent story across locations.',
        '#38bdf8',
      ),
      buildScenario(
        'worst-case',
        '2100 Projection',
        2100,
        'This 2100 Maine view uses the extrapolated California demo curve rather than a Maine-specific inundation model.',
        '#f97316',
      ),
    ],
    defaultHotspotId: 'render-center',
  },
];

export function getLocationBySlug(slug: string) {
  return LOCATIONS.find((location) => location.slug === slug);
}
