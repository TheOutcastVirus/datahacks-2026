export type CameraPose = {
  position: [number, number, number];
  target: [number, number, number];
};

export type ViewerState = 'loading' | 'ready' | 'error';

export type ViewerCommandApi = {
  goToHotspot: (hotspotId: string) => Promise<void>;
  moveCamera: (direction: 'left' | 'right' | 'forward' | 'back') => void;
  zoomCamera: (direction: 'in' | 'out') => void;
  resetCamera: () => void;
  setScenario: (scenarioId: string) => void;
  compareScenario: (leftId: string, rightId: string) => void;
};
