export type CameraPose = {
  position: [number, number, number];
  target: [number, number, number];
};

export type ViewerState = 'loading' | 'ready' | 'error';

export type HazardLabel = 'tall_structure' | 'flood_exposed' | 'erosion_proxy' | string;

export type HazardMarker = {
  id: string;
  label: HazardLabel;
  position: [number, number, number];
  severity: number;
  metrics: Record<string, number>;
  summary: string;
};

export type HazardReport = {
  version: number;
  source: string;
  bbox?: { yMin: number; yMax: number; floodY: number };
  hazards: HazardMarker[];
};

export type ViewerCommandApi = {
  goToHotspot: (hotspotId: string) => Promise<void>;
  moveCamera: (direction: 'left' | 'right' | 'forward' | 'back') => void;
  zoomCamera: (direction: 'in' | 'out') => void;
  resetCamera: () => void;
  setScenario: (scenarioId: string) => void;
  compareScenario: (leftId: string, rightId: string) => void;
  setHazardsVisible: (visible: boolean) => void;
  getHazards: () => HazardMarker[];
};
