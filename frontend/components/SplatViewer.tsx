'use client';

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { Camera, Vector3 } from 'three';
import type { OrbitControls as OrbitControlsType } from 'three/examples/jsm/controls/OrbitControls.js';

import type { SceneHotspot } from '@/lib/locations';
import type {
  CameraPose,
  HazardMarker,
  HazardReport,
  ViewerCommandApi,
  ViewerState,
} from '@/lib/viewer-types';
type SplatGestureMessage =
  | { type: 'splat-hand-control'; action: 'orbit'; dx: number; dy: number }
  | { type: 'splat-hand-control'; action: 'zoom'; delta: number }
  | { type: 'splat-hand-control'; action: 'pan'; dx: number; dy: number }
  | { type: 'splat-hand-control'; action: 'roll'; delta: number }
  | { type: 'splat-hand-control'; action: 'reset' };
type HandStatus =
  | 'inactive'
  | 'initializing'
  | 'requesting-camera'
  | 'tracking'
  | 'no-hand'
  | 'permission-denied'
  | 'error';

type Point2 = { x: number; y: number };
type DetectedHand = 'left' | 'right' | 'unknown';
type GestureMode = 'pan' | 'zoom';
type GestureState = {
  smoothedCenter: Point2 | null;
  smoothedHandScale: number | null;
  peaceZoomActive: boolean;
  activeGesture: GestureMode | null;
};
type CameraSnapshot = {
  position: [number, number, number];
  target: [number, number, number];
  up: [number, number, number];
};
type OrbitCamera = Camera & {
  position: Vector3;
  up: Vector3;
};
type FingerState = {
  index: boolean;
  middle: boolean;
  ring: boolean;
  pinky: boolean;
};
type HandednessPrediction = Array<Array<{ categoryName?: string | null }>> | undefined;
type FloodCalibration = {
  startY: number;
  endY: number;
};
type FloodShader = {
  uniforms: {
    uFloodLevelY: { value: number };
    uFloodBandWidth: { value: number };
    uFloodEdgeSoftness: { value: number };
    uFloodTintStrength: { value: number };
    uFloodColor: { value: import('three').Color };
    uTime: { value: number };
  };
};

const HAND_LANDMARKER_MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
const HAND_LANDMARKER_WASM_URL =
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.34/wasm';
const PALM_INDICES = [0, 5, 9, 13, 17] as const;
const GESTURE_SMOOTHING = 0.35;
const PAN_DEADZONE = 0.16;
const PAN_NORMALIZATION_FLOOR = 0.085;
const PAN_GAIN = 0.018;
const SCALE_ZOOM_DEADZONE = 0.0025;
/** Normalized coords: wrist/thumb must stay inside this margin or we stop (hand leaving frame). */
const HAND_FRAME_MARGIN = 0.04;
/** |cos(thumb angle)| must exceed this to count as left vs right; otherwise stop (ambiguous thumb). */
const THUMB_COS_THRESHOLD = 0.58;

function handLandmarksUsableForThumbSteer(
  landmarks: import('@mediapipe/tasks-vision').NormalizedLandmark[],
): boolean {
  for (const index of [0, 4] as const) {
    const p = landmarks[index];
    if (!p) return false;
    if (p.visibility != null && p.visibility < 0.45) return false;
    if (
      p.x < HAND_FRAME_MARGIN ||
      p.x > 1 - HAND_FRAME_MARGIN ||
      p.y < HAND_FRAME_MARGIN ||
      p.y > 1 - HAND_FRAME_MARGIN
    ) {
      return false;
    }
  }
  return true;
}

const FLOOD_CALIBRATION_BY_URL: Record<string, FloodCalibration> = {
  '/Cabbage-mvs_1012_04.ply': {
    startY: 0.1356126070022583,
    endY: 0.4573782980442047,
  },
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function distance2D(pointA: Point2, pointB: Point2) {
  return Math.hypot(pointA.x - pointB.x, pointA.y - pointB.y);
}

function normalizeAngleDelta(delta: number) {
  return Math.atan2(Math.sin(delta), Math.cos(delta));
}

function getHandednessLabel(
  handedness: HandednessPrediction,
  index: number,
): DetectedHand {
  const label = handedness?.[index]?.[0]?.categoryName?.toLowerCase();
  if (label === 'left' || label === 'right') {
    return label;
  }
  return 'unknown';
}

function getExtendedFingers(
  landmarks: import('@mediapipe/tasks-vision').NormalizedLandmark[],
): FingerState {
  const wrist = landmarks[0];
  const isFingerExtended = (
    tipIndex: number,
    dipIndex: number,
    pipIndex: number,
    mcpIndex: number,
  ) => {
    const tipDistance = distance2D(landmarks[tipIndex], wrist);
    const dipDistance = distance2D(landmarks[dipIndex], wrist);
    const pipDistance = distance2D(landmarks[pipIndex], wrist);
    const mcpDistance = distance2D(landmarks[mcpIndex], wrist);
    return tipDistance > dipDistance * 1.04 && tipDistance > pipDistance * 1.1 && tipDistance > mcpDistance * 1.18;
  };

  return {
    index: isFingerExtended(8, 7, 6, 5),
    middle: isFingerExtended(12, 11, 10, 9),
    ring: isFingerExtended(16, 15, 14, 13),
    pinky: isFingerExtended(20, 19, 18, 17),
  };
}

function describeTrackedHand(handedness: DetectedHand) {
  if (handedness === 'right') return 'right hand';
  if (handedness === 'left') return 'left hand';
  return 'visible hand';
}

function getCameraSnapshot(controls: OrbitControlsType): CameraSnapshot {
  const camera = controls.object as OrbitCamera;

  return {
    position: [camera.position.x, camera.position.y, camera.position.z],
    target: [controls.target.x, controls.target.y, controls.target.z],
    up: [camera.up.x, camera.up.y, camera.up.z],
  };
}

function resetOrbitCamera(controls: OrbitControlsType, snapshot: CameraSnapshot | null) {
  if (!snapshot) return;

  const camera = controls.object as OrbitCamera;
  camera.position.set(...snapshot.position);
  camera.up.set(...snapshot.up);
  controls.target.set(...snapshot.target);
  controls.update();
}

function panOrbitCamera(controls: OrbitControlsType, dx: number, dy: number) {
  const camera = controls.object as OrbitCamera;

  const forward = controls.target.clone().sub(camera.position).normalize();
  const right = forward.clone().cross(camera.up).normalize();
  const up = camera.up.clone().normalize();
  const distance = camera.position.distanceTo(controls.target);
  const movementScale = Math.max(distance * 0.48, 0.015);
  const movement = right.multiplyScalar(dx * movementScale).add(up.multiplyScalar(-dy * movementScale));

  camera.position.add(movement);
  controls.target.add(movement);
  controls.update();
}

function rollOrbitCamera(controls: OrbitControlsType, delta: number) {
  const camera = controls.object as OrbitCamera;
  const forward = controls.target.clone().sub(camera.position).normalize();
  camera.up.applyAxisAngle(forward, delta);
  camera.up.normalize();
  controls.update();
}
function lerp(start: number, end: number, amount: number) {
  return start + (end - start) * amount;
}

function computeWorldYBounds(
  localBox: { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } },
  rx: number,
  ry: number,
  rz: number,
): FloodCalibration {
  // Euler XYZ: R = Rz * Ry * Rx — extract row 1 (world Y) coefficients
  const cx = Math.cos(rx), sx = Math.sin(rx);
  const cy = Math.cos(ry), sy = Math.sin(ry);
  const cz = Math.cos(rz), sz = Math.sin(rz);
  const m10 = cy * sz;
  const m11 = cx * cz + sx * sy * sz;
  const m12 = cx * sy * sz - cz * sx;
  const { min, max } = localBox;
  const xs = [min.x, max.x];
  const ys = [min.y, max.y];
  const zs = [min.z, max.z];
  let minY = Infinity, maxY = -Infinity;
  for (const x of xs) for (const y of ys) for (const z of zs) {
    const wy = m10 * x + m11 * y + m12 * z;
    if (wy < minY) minY = wy;
    if (wy > maxY) maxY = wy;
  }
  return { startY: minY, endY: maxY };
}

function resolveFloodCalibration(
  splatUrl: string,
  boundingBox: import('three').Box3 | null | undefined,
): FloodCalibration {
  const calibrated = FLOOD_CALIBRATION_BY_URL[splatUrl];
  if (calibrated) return calibrated;

  return {
    startY: boundingBox?.min.y ?? 0,
    endY: boundingBox?.max.y ?? 1,
  };
}
function sendSplatGesture(
  targetWindow: Window | null | undefined,
  message: SplatGestureMessage,
) {
  if (!targetWindow) return;

  type SplatControlWindow = Window & {
    __splatHandControl?: {
      orbit?: (dx: number, dy: number) => void;
      zoom?: (delta: number) => void;
      pan?: (dx: number, dy: number) => void;
      roll?: (delta: number) => void;
      reset?: () => void;
    };
  };

  const splatWindow = targetWindow as SplatControlWindow;
  if (message.action === 'orbit') {
    splatWindow.__splatHandControl?.orbit?.(message.dx, message.dy);
  } else if (message.action === 'zoom') {
    splatWindow.__splatHandControl?.zoom?.(message.delta);
  } else if (message.action === 'pan') {
    splatWindow.__splatHandControl?.pan?.(message.dx, message.dy);
  } else if (message.action === 'roll') {
    splatWindow.__splatHandControl?.roll?.(message.delta);
  } else {
    splatWindow.__splatHandControl?.reset?.();
  }

  splatWindow.postMessage(message, location.origin);
}

const noopViewerApi: ViewerCommandApi = {
  async goToHotspot() {},
  moveCamera() {},
  zoomCamera() {},
  resetCamera() {},
  setScenario() {},
  compareScenario() {},
  setHazardsVisible() {},
  getHazards: () => [],
};

const HAZARD_LABEL_COLOR: Record<string, string> = {
  tall_structure: '#38bdf8',
  flood_exposed: '#f97316',
  erosion_proxy: '#f59e0b',
};

function hazardLetterTexture(
  THREE: typeof import('three'),
  letter: string,
  color: string,
) {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.clearRect(0, 0, size, size);
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 10, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(3, 12, 22, 0.92)';
    ctx.fill();
    ctx.lineWidth = 8;
    ctx.strokeStyle = color;
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = 'bold 140px system-ui, -apple-system, Segoe UI, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(letter, size / 2, size / 2 + 8);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.anisotropy = 4;
  return texture;
}

type SplatViewerProps = {
  splatUrl: string;
  renderer?: 'auto' | 'ply' | 'splat';
  floodProgress?: number;
  hotspots?: SceneHotspot[];
  hazardsUrl?: string;
  onViewerStateChange?: (state: ViewerState) => void;
};

type HazardTooltipState = {
  hazard: HazardMarker;
  x: number;
  y: number;
};

const SplatViewer = forwardRef<ViewerCommandApi, SplatViewerProps>(function SplatViewer(
  {
    splatUrl,
    renderer = 'auto',
    floodProgress = 0,
    hotspots = [],
    hazardsUrl,
    onViewerStateChange,
  },
  ref,
) {
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoOverlayRef = useRef<HTMLCanvasElement>(null);
  const controlsRef = useRef<OrbitControlsType | null>(null);
  const resetCameraRef = useRef<CameraSnapshot | null>(null);
  const floodShaderRef = useRef<FloodShader | null>(null);
  const floodCalibrationRef = useRef<FloodCalibration | null>(null);
  const localBBoxRef = useRef<{ min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } } | null>(null);
  const floodProgressRef = useRef(clamp(floodProgress, 0, 1));
  const pointsRef = useRef<import('three').Points | null>(null);
  const fitCameraRef = useRef<(() => void) | null>(null);

  const [rotX, setRotX] = useState(-1.327);
  const [rotY, setRotY] = useState(0.640);
  const [rotZ, setRotZ] = useState(0.030);
  const [camElev, setCamElev] = useState(0.238);
  const [camDist, setCamDist] = useState(0.359);
  const [showSetup, setShowSetup] = useState(false);
  const [camPos, setCamPos] = useState<{ x: number; y: number; z: number } | null>(null);
  const camElevRef = useRef(0.238);
  const camDistRef = useRef(0.359);
  const gestureStateRef = useRef<GestureState>({
    smoothedCenter: null,
    smoothedHandScale: null,
    peaceZoomActive: false,
    activeGesture: null,
  });
  const thumbKeyRef = useRef<string | null>(null);
  const handStatusRef = useRef<HandStatus>('inactive');
  const handStatusDetailRef = useRef<string>('Hand control off');
  const actionApiRef = useRef<ViewerCommandApi>(noopViewerApi);
  const isPlyAsset = splatUrl.toLowerCase().endsWith('.ply');
  const usePlyRenderer = renderer === 'ply' || (renderer === 'auto' && isPlyAsset);
  const hotspotMap = useMemo(
    () => new Map(hotspots.map((hotspot) => [hotspot.id, hotspot])),
    [hotspots],
  );
  const clampedFloodProgress = clamp(floodProgress, 0, 1);
  const [viewerState, setViewerState] = useState<ViewerState>(
    usePlyRenderer ? 'loading' : 'ready',
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [handControlEnabled, setHandControlEnabled] = useState(false);
  const [handStatus, setHandStatus] = useState<HandStatus>('inactive');
  const [hazards, setHazards] = useState<HazardMarker[]>([]);
  const [hazardTooltip, setHazardTooltip] = useState<HazardTooltipState | null>(null);
  const hazardsRef = useRef<HazardMarker[]>([]);
  const hazardGroupRef = useRef<import('three').Group | null>(null);
  const hazardsVisibleRef = useRef<boolean>(false);
  const hazardRebuildRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    hazardsRef.current = hazards;
    hazardRebuildRef.current?.();
  }, [hazards]);

  useEffect(() => {
    let cancelled = false;
    if (!hazardsUrl) {
      setHazards([]);
      return;
    }
    (async () => {
      try {
        const response = await fetch(hazardsUrl);
        if (!response.ok) return;
        const payload = (await response.json()) as HazardReport;
        if (!cancelled && Array.isArray(payload.hazards)) {
          setHazards(payload.hazards);
        }
      } catch {
        // ignore — hazards are optional
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hazardsUrl]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.code === 'KeyH' &&
        !e.metaKey &&
        !e.ctrlKey &&
        !e.altKey &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement)
      ) {
        setHandControlEnabled((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const [handStatusDetail, setHandStatusDetail] = useState('Hand control off');

  const splatIframeSrc = useMemo(
    () => `/splat/viewer.html?url=${encodeURIComponent(splatUrl)}&zoom=${camDistRef.current}`,
    [splatUrl],
  );

  useImperativeHandle(
    ref,
    () => ({
      goToHotspot: (hotspotId) => actionApiRef.current.goToHotspot(hotspotId),
      moveCamera: (direction) => actionApiRef.current.moveCamera(direction),
      zoomCamera: (direction) => actionApiRef.current.zoomCamera(direction),
      resetCamera: () => actionApiRef.current.resetCamera(),
      setScenario: (scenarioId) => actionApiRef.current.setScenario(scenarioId),
      compareScenario: (leftId, rightId) =>
        actionApiRef.current.compareScenario(leftId, rightId),
      setHazardsVisible: (visible) => actionApiRef.current.setHazardsVisible(visible),
      getHazards: () => actionApiRef.current.getHazards(),
    }),
    [],
  );

  useEffect(() => {
    onViewerStateChange?.(viewerState);
  }, [onViewerStateChange, viewerState]);

  useEffect(() => {
    floodProgressRef.current = clampedFloodProgress;

    const floodShader = floodShaderRef.current;
    const floodCalibration = floodCalibrationRef.current;
    if (!floodShader || !floodCalibration) return;

    floodShader.uniforms.uFloodLevelY.value = lerp(
      floodCalibration.startY,
      floodCalibration.endY,
      clampedFloodProgress,
    );
  }, [clampedFloodProgress]);

  useEffect(() => {
    if (usePlyRenderer) return;
    iframeRef.current?.contentWindow?.postMessage(
      { type: 'splat-flood-progress', value: clampedFloodProgress },
      '*',
    );
  }, [clampedFloodProgress, usePlyRenderer]);

  useEffect(() => {
    actionApiRef.current = noopViewerApi;

    if (usePlyRenderer) {
      return;
    }

    const splatWindow = () => iframeRef.current?.contentWindow ?? null;
    const pressKey = (code: string) => {
      splatWindow()?.postMessage({ type: 'splat-keydown', code }, location.origin);
      window.setTimeout(() => {
        splatWindow()?.postMessage({ type: 'splat-keyup', code }, location.origin);
      }, 140);
    };

    actionApiRef.current = {
      async goToHotspot() {},
      moveCamera(direction) {
        const codeMap = {
          left: 'KeyA',
          right: 'KeyD',
          forward: 'KeyW',
          back: 'KeyS',
        } as const;
        pressKey(codeMap[direction]);
      },
      zoomCamera(direction) {
        sendSplatGesture(splatWindow(), {
          type: 'splat-hand-control',
          action: 'zoom',
          delta: direction === 'in' ? -0.45 : 0.45,
        });
      },
      resetCamera() {},
      setScenario() {},
      compareScenario() {},
      setHazardsVisible() {},
      getHazards: () => hazardsRef.current,
    };

    const moveKeys = new Set([
      'KeyW',
      'KeyS',
      'KeyA',
      'KeyD',
      'ArrowUp',
      'ArrowDown',
      'ArrowLeft',
      'ArrowRight',
      'KeyQ',
      'KeyE',
      'Space',
    ]);
    const forward = (event: KeyboardEvent) => {
      if (!moveKeys.has(event.code)) return;
      event.preventDefault();
      iframeRef.current?.contentWindow?.postMessage(
        { type: 'splat-keydown', code: event.code },
        '*',
      );
    };
    const release = (event: KeyboardEvent) => {
      if (!moveKeys.has(event.code)) return;
      iframeRef.current?.contentWindow?.postMessage(
        { type: 'splat-keyup', code: event.code },
        '*',
      );
    };
    window.addEventListener('keydown', forward);
    window.addEventListener('keyup', release);
    return () => {
      window.removeEventListener('keydown', forward);
      window.removeEventListener('keyup', release);
    };
  }, [clampedFloodProgress, usePlyRenderer]);

  useEffect(() => {
    if (!usePlyRenderer) {
      return;
    }

    const canvasHost = canvasHostRef.current;
    if (!canvasHost) return;

    floodShaderRef.current = null;
    floodCalibrationRef.current = null;

    let isDisposed = false;
    let animationFrameId = 0;
    let resizeObserver: ResizeObserver | null = null;

    let rendererInstance: import('three').WebGLRenderer | null = null;
    let controls: OrbitControlsType | null = null;
    let geometryToDispose: import('three').BufferGeometry | null = null;
    let materialToDispose: import('three').Material | null = null;
    let onKeyDown: ((event: KeyboardEvent) => void) | null = null;
    let onKeyUp: ((event: KeyboardEvent) => void) | null = null;
    let onPointerMove: ((event: PointerEvent) => void) | null = null;
    let onPointerLeave: ((event: PointerEvent) => void) | null = null;
    let transition:
      | {
          start: number;
          duration: number;
          fromPosition: import('three').Vector3;
          toPosition: import('three').Vector3;
          fromTarget: import('three').Vector3;
          toTarget: import('three').Vector3;
          resolve: () => void;
        }
      | null = null;

    const boot = async () => {
      try {
        setViewerState('loading');
        setErrorMessage(null);

        const THREE = await import('three');
        const [{ OrbitControls }, { PLYLoader }] = await Promise.all([
          import('three/examples/jsm/controls/OrbitControls.js'),
          import('three/examples/jsm/loaders/PLYLoader.js'),
        ]);

        if (isDisposed) return;

        const scene = new THREE.Scene();
        scene.background = new THREE.Color('#020a12');

        const camera = new THREE.PerspectiveCamera(42, 1, 0.001, 100);
        let initialPose: CameraPose | null = null;

        rendererInstance = new THREE.WebGLRenderer({
          antialias: true,
          alpha: false,
          powerPreference: 'high-performance',
        });
        rendererInstance.outputColorSpace = THREE.SRGBColorSpace;
        rendererInstance.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        rendererInstance.domElement.style.width = '100%';
        rendererInstance.domElement.style.height = '100%';
        rendererInstance.domElement.style.display = 'block';

        canvasHost.replaceChildren(rendererInstance.domElement);

        controls = new OrbitControls(camera, rendererInstance.domElement);
        controlsRef.current = controls;
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.rotateSpeed = 0.55;
        controls.zoomSpeed = 1.2;
        controls.panSpeed = 0.9;
        controls.screenSpacePanning = false;

        const loader = new PLYLoader();
        const loadedGeometry = await loader.loadAsync(splatUrl);
        if (isDisposed) {
          loadedGeometry.dispose();
          return;
        }

        loadedGeometry.computeBoundingBox();
        loadedGeometry.computeBoundingSphere();
        geometryToDispose = loadedGeometry;
        const rawBox = loadedGeometry.boundingBox;
        const localBox = rawBox
          ? { min: { x: rawBox.min.x, y: rawBox.min.y, z: rawBox.min.z }, max: { x: rawBox.max.x, y: rawBox.max.y, z: rawBox.max.z } }
          : { min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } };
        localBBoxRef.current = localBox;
        const floodCalibration = computeWorldYBounds(localBox, rotX, rotY, rotZ);
        floodCalibrationRef.current = floodCalibration;
        const initialFloodLevelY = lerp(
          floodCalibration.startY,
          floodCalibration.endY,
          floodProgressRef.current,
        );

        const boundingSphere =
          loadedGeometry.boundingSphere ?? new THREE.Sphere(new THREE.Vector3(), 1);
        const radius = Math.max(boundingSphere.radius, 0.01);
        const center = boundingSphere.center.clone();
        const pointCount = loadedGeometry.getAttribute('position').count;
        const pointSize = Math.min(
          Math.max((radius / Math.cbrt(pointCount || 1)) * 1.6, 0.0015),
          0.012,
        );

        const hasVertexColors = loadedGeometry.getAttribute('color') !== undefined;
        const pointsMaterial = new THREE.PointsMaterial({
          size: pointSize,
          sizeAttenuation: true,
          vertexColors: hasVertexColors,
          ...(hasVertexColors ? {} : { color: '#d7e3f4' }),
        });
        pointsMaterial.onBeforeCompile = shader => {
          shader.uniforms.uFloodLevelY = { value: initialFloodLevelY };
          shader.uniforms.uFloodBandWidth = { value: 0.018 };
          shader.uniforms.uFloodEdgeSoftness = { value: 0.012 };
          shader.uniforms.uFloodTintStrength = { value: 0.58 };
          shader.uniforms.uFloodColor = { value: new THREE.Color('#167d96') };
          shader.uniforms.uTime = { value: performance.now() / 1000 };

          shader.vertexShader = `
            varying float vPointY;
          ${shader.vertexShader}`.replace(
            '#include <begin_vertex>',
            `#include <begin_vertex>
            vPointY = (modelMatrix * vec4(position, 1.0)).y;`,
          );

          shader.fragmentShader = `
            uniform float uFloodLevelY;
            uniform float uFloodBandWidth;
            uniform float uFloodEdgeSoftness;
            uniform float uFloodTintStrength;
            uniform vec3 uFloodColor;
            uniform float uTime;
            varying float vPointY;
          ${shader.fragmentShader}`.replace(
            '#include <color_fragment>',
            `#include <color_fragment>
            float submerged = smoothstep(
              uFloodLevelY + uFloodEdgeSoftness,
              uFloodLevelY - uFloodEdgeSoftness,
              vPointY
            );

            float band = 1.0 - smoothstep(
              0.0,
              uFloodBandWidth,
              abs(vPointY - uFloodLevelY)
            );

            float pulse = 0.88 + 0.12 * sin(uTime * 1.6 + vPointY * 24.0);

            diffuseColor.rgb = mix(
              diffuseColor.rgb,
              uFloodColor,
              submerged * uFloodTintStrength
            );
            diffuseColor.rgb += band * pulse * vec3(0.05, 0.10, 0.13);`,
          );

          floodShaderRef.current = shader as unknown as FloodShader;
        };
        pointsMaterial.customProgramCacheKey = () => 'ply-flood-v1';
        materialToDispose = pointsMaterial;

        const points = new THREE.Points(loadedGeometry, pointsMaterial);
        pointsRef.current = points;
        scene.add(points);

        const hazardGroup = new THREE.Group();
        hazardGroup.visible = hazardsVisibleRef.current;
        scene.add(hazardGroup);
        hazardGroupRef.current = hazardGroup;
        const hazardSpriteTextures: import('three').Texture[] = [];

        const rebuildHazardSprites = () => {
          while (hazardGroup.children.length > 0) {
            const child = hazardGroup.children.pop();
            if (child && (child as import('three').Sprite).material) {
              ((child as import('three').Sprite).material as import('three').SpriteMaterial).dispose();
            }
          }
          for (const texture of hazardSpriteTextures.splice(0)) texture.dispose();
          const scale = Math.max(radius * 0.08, 0.08);
          for (const hazard of hazardsRef.current) {
            const color = HAZARD_LABEL_COLOR[hazard.label] ?? '#00d4b4';
            const texture = hazardLetterTexture(THREE, hazard.id, color);
            hazardSpriteTextures.push(texture);
            const material = new THREE.SpriteMaterial({
              map: texture,
              transparent: true,
              depthTest: false,
              depthWrite: false,
            });
            const sprite = new THREE.Sprite(material);
            sprite.position.set(hazard.position[0], hazard.position[1], hazard.position[2]);
            sprite.scale.set(scale, scale, scale);
            sprite.renderOrder = 999;
            sprite.userData.hazardId = hazard.id;
            hazardGroup.add(sprite);
          }
        };
        rebuildHazardSprites();
        hazardRebuildRef.current = rebuildHazardSprites;

        const raycaster = new THREE.Raycaster();
        raycaster.params.Sprite = { threshold: 0.1 } as unknown as never;
        const pointerVec = new THREE.Vector2();
        onPointerMove = (event: PointerEvent) => {
          if (!hazardGroup.visible || hazardGroup.children.length === 0) {
            setHazardTooltip((current) => (current ? null : current));
            return;
          }
          const rect = rendererInstance!.domElement.getBoundingClientRect();
          const x = event.clientX - rect.left;
          const y = event.clientY - rect.top;
          pointerVec.x = (x / rect.width) * 2 - 1;
          pointerVec.y = -(y / rect.height) * 2 + 1;
          raycaster.setFromCamera(pointerVec, camera);
          const hits = raycaster.intersectObjects(hazardGroup.children, false);
          if (hits.length > 0) {
            const hazardId = hits[0].object.userData.hazardId as string | undefined;
            const hazard = hazardsRef.current.find((h) => h.id === hazardId);
            if (hazard) {
              setHazardTooltip({ hazard, x, y });
              return;
            }
          }
          setHazardTooltip((current) => (current ? null : current));
        };
        onPointerLeave = () => setHazardTooltip((current) => (current ? null : current));
        rendererInstance.domElement.addEventListener('pointermove', onPointerMove);
        rendererInstance.domElement.addEventListener('pointerleave', onPointerLeave);

        const readPose = (): CameraPose => ({
          position: [camera.position.x, camera.position.y, camera.position.z],
          target: [controls!.target.x, controls!.target.y, controls!.target.z],
        });

        const animateToPose = (pose: CameraPose, duration = 900) => {
          transition?.resolve();
          return new Promise<void>((resolve) => {
            transition = {
              start: performance.now(),
              duration,
              fromPosition: camera.position.clone(),
              toPosition: new THREE.Vector3(...pose.position),
              fromTarget: controls!.target.clone(),
              toTarget: new THREE.Vector3(...pose.target),
              resolve,
            };
          });
        };

        const fitCamera = () => {
          if (!rendererInstance) return;

          const width = Math.max(canvasHost.clientWidth, 1);
          const height = Math.max(canvasHost.clientHeight, 1);

          camera.aspect = width / height;
          camera.near = Math.max(radius / 200, 0.001);
          camera.far = Math.max(radius * 25, 10);
          camera.updateProjectionMatrix();

          const fovRadians = (camera.fov * Math.PI) / 180;
          const distance = (radius / Math.tan(fovRadians / 2)) * camDistRef.current;

          camera.position.set(
            center.x,
            center.y + distance * camElevRef.current,
            center.z + distance,
          );
          controls?.target.copy(center);
          controls?.update();
          if (controls) {
            resetCameraRef.current = getCameraSnapshot(controls);
          }

          initialPose = readPose();
          rendererInstance.setSize(width, height, false);
          rendererInstance.render(scene, camera);
        };

        const moveCamera = (direction: 'left' | 'right' | 'forward' | 'back') => {
          if (!controls) return;
          const speed = radius * 0.18;
          const forward = camera.getWorldDirection(new THREE.Vector3());
          const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize();
          if (direction === 'forward') {
            camera.position.addScaledVector(forward, speed);
            controls.target.addScaledVector(forward, speed);
          }
          if (direction === 'back') {
            camera.position.addScaledVector(forward, -speed);
            controls.target.addScaledVector(forward, -speed);
          }
          if (direction === 'left') {
            camera.position.addScaledVector(right, -speed);
            controls.target.addScaledVector(right, -speed);
          }
          if (direction === 'right') {
            camera.position.addScaledVector(right, speed);
            controls.target.addScaledVector(right, speed);
          }
          controls.update();
        };

        fitCameraRef.current = fitCamera;
        fitCamera();
        resizeObserver = new ResizeObserver(fitCamera);
        resizeObserver.observe(canvasHost);

        actionApiRef.current = {
          async goToHotspot(hotspotId) {
            const hotspot = hotspotMap.get(hotspotId);
            if (!hotspot) return;
            await animateToPose(hotspot.cameraPose);
          },
          moveCamera(direction) {
            moveCamera(direction);
          },
          zoomCamera(direction) {
            if (!controls) return;
            const zoomScale = direction === 'in' ? 1.22 : 0.82;
            if (direction === 'in') {
              controls.dollyIn(zoomScale);
            } else {
              controls.dollyOut(1 / zoomScale);
            }
            controls.update();
          },
          resetCamera() {
            if (!initialPose) return;
            void animateToPose(initialPose, 750);
          },
          setScenario() {},
          compareScenario() {},
          setHazardsVisible(visible) {
            hazardsVisibleRef.current = visible;
            if (hazardGroupRef.current) {
              hazardGroupRef.current.visible = visible;
            }
            if (!visible) {
              setHazardTooltip(null);
            }
          },
          getHazards: () => hazardsRef.current,
        };

        const moveKeys = new Set([
          'KeyW',
          'KeyS',
          'KeyA',
          'KeyD',
          'ArrowUp',
          'ArrowDown',
          'ArrowLeft',
          'ArrowRight',
        ]);
        const keysDown = new Set<string>();
        onKeyDown = (event: KeyboardEvent) => {
          if (moveKeys.has(event.code)) event.preventDefault();
          keysDown.add(event.code);
        };
        onKeyUp = (event: KeyboardEvent) => keysDown.delete(event.code);
        window.addEventListener('keydown', onKeyDown);
        window.addEventListener('keyup', onKeyUp);

        const animate = () => {
          if (isDisposed || !rendererInstance || !controls) return;

          if (transition) {
            const progress = Math.min(
              1,
              (performance.now() - transition.start) / transition.duration,
            );
            const eased = 1 - (1 - progress) ** 3;
            camera.position.set(
              transition.fromPosition.x +
                (transition.toPosition.x - transition.fromPosition.x) * eased,
              transition.fromPosition.y +
                (transition.toPosition.y - transition.fromPosition.y) * eased,
              transition.fromPosition.z +
                (transition.toPosition.z - transition.fromPosition.z) * eased,
            );
            controls.target.set(
              transition.fromTarget.x +
                (transition.toTarget.x - transition.fromTarget.x) * eased,
              transition.fromTarget.y +
                (transition.toTarget.y - transition.fromTarget.y) * eased,
              transition.fromTarget.z +
                (transition.toTarget.z - transition.fromTarget.z) * eased,
            );
            if (progress >= 1) {
              const resolve = transition.resolve;
              transition = null;
              resolve();
            }
          }

          const floodShader = floodShaderRef.current;
          const activeFloodCalibration = floodCalibrationRef.current;
          if (floodShader && activeFloodCalibration) {
            floodShader.uniforms.uTime.value = performance.now() / 1000;
            floodShader.uniforms.uFloodLevelY.value = lerp(
              activeFloodCalibration.startY,
              activeFloodCalibration.endY,
              floodProgressRef.current,
            );
          }

          if (keysDown.size > 0) {
            const speed = radius * 0.014;
            const forward = camera.getWorldDirection(new THREE.Vector3());
            const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize();
            if (keysDown.has('KeyW') || keysDown.has('ArrowUp')) {
              camera.position.addScaledVector(forward, speed);
              controls.target.addScaledVector(forward, speed);
            }
            if (keysDown.has('KeyS') || keysDown.has('ArrowDown')) {
              camera.position.addScaledVector(forward, -speed);
              controls.target.addScaledVector(forward, -speed);
            }
            if (keysDown.has('KeyA') || keysDown.has('ArrowLeft')) {
              camera.position.addScaledVector(right, -speed);
              controls.target.addScaledVector(right, -speed);
            }
            if (keysDown.has('KeyD') || keysDown.has('ArrowRight')) {
              camera.position.addScaledVector(right, speed);
              controls.target.addScaledVector(right, speed);
            }
          }

          controls.update();
          rendererInstance.render(scene, camera);
          animationFrameId = window.requestAnimationFrame(animate);
        };

        animationFrameId = window.requestAnimationFrame(animate);
        setViewerState('ready');
      } catch (error) {
        if (isDisposed) return;
        setViewerState('error');
        setErrorMessage(error instanceof Error ? error.message : 'Unable to load PLY scene');
      }
    };

    void boot();

    return () => {
      isDisposed = true;
      window.cancelAnimationFrame(animationFrameId);
      resizeObserver?.disconnect();
      if (onKeyDown) window.removeEventListener('keydown', onKeyDown);
      if (onKeyUp) window.removeEventListener('keyup', onKeyUp);
      if (rendererInstance && onPointerMove) {
        rendererInstance.domElement.removeEventListener('pointermove', onPointerMove);
      }
      if (rendererInstance && onPointerLeave) {
        rendererInstance.domElement.removeEventListener('pointerleave', onPointerLeave);
      }
      hazardGroupRef.current = null;
      hazardRebuildRef.current = null;
      controls?.dispose();
      controlsRef.current = null;
      resetCameraRef.current = null;
      floodShaderRef.current = null;
      floodCalibrationRef.current = null;
      geometryToDispose?.dispose();
      materialToDispose?.dispose();
      rendererInstance?.dispose();
      actionApiRef.current = noopViewerApi;
      canvasHost.replaceChildren();
    };
  }, [hotspotMap, splatUrl, usePlyRenderer]);

  useEffect(() => {
    if (!handControlEnabled || viewerState !== 'ready') return;

    const videoElement = videoRef.current;
    let isDisposed = false;
    let animationFrameId = 0;
    let stream: MediaStream | null = null;
    let handLandmarker: import('@mediapipe/tasks-vision').HandLandmarker | null = null;
    let drawingUtils: import('@mediapipe/tasks-vision').DrawingUtils | null = null;

    const releaseThumbKeys = () => {
      const held = thumbKeyRef.current;
      if (!held) return;
      window.dispatchEvent(new KeyboardEvent('keyup', { code: held, bubbles: true }));
      iframeRef.current?.contentWindow?.postMessage({ type: 'splat-keyup', code: held }, '*');
      thumbKeyRef.current = null;
    };

    const resetGestureState = () => {
      releaseThumbKeys();
      gestureStateRef.current = {
        smoothedCenter: null,
        smoothedHandScale: null,
        peaceZoomActive: false,
        activeGesture: null,
      };
    };

    const updateHandStatus = (nextStatus: HandStatus, detail: string) => {
      if (
        handStatusRef.current === nextStatus &&
        handStatusDetailRef.current === detail
      ) {
        return;
      }
      handStatusRef.current = nextStatus;
      handStatusDetailRef.current = detail;
      setHandStatus(nextStatus);
      setHandStatusDetail(detail);
    };

    const clearOverlay = () => {
      const overlay = videoOverlayRef.current;
      if (!overlay) return;
      const context = overlay.getContext('2d');
      if (!context) return;
      context.clearRect(0, 0, overlay.width, overlay.height);
    };

    const drawLandmarks = (
      landmarkSets:
        | import('@mediapipe/tasks-vision').NormalizedLandmark[][]
        | undefined,
      mediaPipe: typeof import('@mediapipe/tasks-vision'),
    ) => {
      const overlay = videoOverlayRef.current;
      const video = videoRef.current;
      if (!overlay || !video) return;

      const width = video.videoWidth || 320;
      const height = video.videoHeight || 240;
      if (overlay.width !== width) overlay.width = width;
      if (overlay.height !== height) overlay.height = height;

      const context = overlay.getContext('2d');
      if (!context) return;
      context.clearRect(0, 0, width, height);

      if (!landmarkSets?.length) return;

      drawingUtils ??= new mediaPipe.DrawingUtils(context);
      for (const landmarks of landmarkSets) {
        drawingUtils.drawConnectors(landmarks, mediaPipe.HandLandmarker.HAND_CONNECTIONS, {
          color: 'rgba(0, 212, 180, 0.85)',
          lineWidth: 2,
        });
        drawingUtils.drawLandmarks(landmarks, {
          color: '#d6f0f8',
          fillColor: '#00d4b4',
          lineWidth: 1,
          radius: 3,
        });
        // Highlight thumb tip (4) and index tip (8) as large green dots
        for (const idx of [4, 8] as const) {
          const lm = landmarks[idx];
          if (!lm) continue;
          context.beginPath();
          context.arc(lm.x * width, lm.y * height, 10, 0, Math.PI * 2);
          context.fillStyle = '#22c55e';
          context.fill();
          context.strokeStyle = '#ffffff';
          context.lineWidth = 2;
          context.stroke();
        }
      }
    };

    const boot = async () => {
      try {
        if (!window.isSecureContext && location.hostname !== 'localhost') {
          updateHandStatus('error', 'Webcam access requires HTTPS or localhost.');
          return;
        }
        if (!navigator.mediaDevices?.getUserMedia) {
          updateHandStatus('error', 'This browser does not support webcam access.');
          return;
        }

        updateHandStatus('initializing', 'Loading MediaPipe hand tracking…');
        const mediaPipe = await import('@mediapipe/tasks-vision');
        if (isDisposed) return;

        const vision = await mediaPipe.FilesetResolver.forVisionTasks(
          HAND_LANDMARKER_WASM_URL,
        );
        if (isDisposed) return;

        handLandmarker = await mediaPipe.HandLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: HAND_LANDMARKER_MODEL_URL,
            delegate: 'GPU',
          },
          runningMode: 'VIDEO',
          numHands: 2,
          minHandDetectionConfidence: 0.65,
          minHandPresenceConfidence: 0.65,
          minTrackingConfidence: 0.6,
        });
        if (isDisposed) return;

        updateHandStatus('requesting-camera', 'Waiting for webcam permission…');
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: 'user',
            width: { ideal: 640 },
            height: { ideal: 480 },
          },
          audio: false,
        });
        if (isDisposed) return;

        if (!videoElement) return;
        videoElement.srcObject = stream;
        videoElement.muted = true;
        videoElement.playsInline = true;
        await videoElement.play();
        if (isDisposed) return;

        updateHandStatus(
          'no-hand',
          'Show your hand. Move it left/right to pan.',
        );

        const step = () => {
          if (isDisposed) return;

          const controls = controlsRef.current;
          const currentVideo = videoRef.current;
          const splatWindow = iframeRef.current?.contentWindow ?? null;
          if (
            !currentVideo ||
            !handLandmarker ||
            (usePlyRenderer ? !controls : !splatWindow)
          ) {
            animationFrameId = window.requestAnimationFrame(step);
            return;
          }

          if (currentVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
            animationFrameId = window.requestAnimationFrame(step);
            return;
          }

          const result = handLandmarker.detectForVideo(
            currentVideo,
            performance.now(),
          );
          const landmarksSet = result.landmarks;
          drawLandmarks(landmarksSet, mediaPipe);

          const handCount = landmarksSet?.length ?? 0;
          if (!handCount) {
            resetGestureState();
            updateHandStatus(
              'no-hand',
              'Show your hand. Move it left/right to pan.',
            );
            animationFrameId = window.requestAnimationFrame(step);
            return;
          }

          const primaryHandIndex = landmarksSet.findIndex((_, index) => {
            return getHandednessLabel(result.handedness as HandednessPrediction, index) === 'right';
          });
          const handIndex = primaryHandIndex >= 0 ? primaryHandIndex : 0;
          const landmarks = landmarksSet[handIndex];
          const trackedHand = getHandednessLabel(
            result.handedness as HandednessPrediction,
            handIndex,
          );

          if (!landmarks?.length) {
            resetGestureState();
            updateHandStatus(
              'no-hand',
              'Show your hand. Point thumb left/right to move.',
            );
            animationFrameId = window.requestAnimationFrame(step);
            return;
          }

          if (!handLandmarksUsableForThumbSteer(landmarks)) {
            resetGestureState();
            updateHandStatus(
              'no-hand',
              'Hand out of frame — keep wrist and thumb visible.',
            );
            animationFrameId = window.requestAnimationFrame(step);
            return;
          }

          const palmCenter = PALM_INDICES.reduce(
            (sum, index) => ({
              x: sum.x + landmarks[index].x / PALM_INDICES.length,
              y: sum.y + landmarks[index].y / PALM_INDICES.length,
            }),
            { x: 0, y: 0 },
          );
          const handScale =
            (
              Math.hypot(landmarks[0].x - landmarks[5].x, landmarks[0].y - landmarks[5].y) +
              Math.hypot(landmarks[0].x - landmarks[9].x, landmarks[0].y - landmarks[9].y) +
              Math.hypot(landmarks[0].x - landmarks[17].x, landmarks[0].y - landmarks[17].y)
            ) / 3;
          const smoothedCenter = gestureStateRef.current.smoothedCenter
            ? {
                x: gestureStateRef.current.smoothedCenter.x + (palmCenter.x - gestureStateRef.current.smoothedCenter.x) * GESTURE_SMOOTHING,
                y: gestureStateRef.current.smoothedCenter.y + (palmCenter.y - gestureStateRef.current.smoothedCenter.y) * GESTURE_SMOOTHING,
              }
            : palmCenter;
          const smoothedHandScale =
            gestureStateRef.current.smoothedHandScale === null
              ? handScale
              : gestureStateRef.current.smoothedHandScale + (handScale - gestureStateRef.current.smoothedHandScale) * GESTURE_SMOOTHING;

          // Thumb direction: angle from wrist (0) to thumb tip (4)
          // Video is mirrored on display, so raw-right = screen-left and vice versa
          const thumbAngle = Math.atan2(
            landmarks[4].y - landmarks[0].y,
            landmarks[4].x - landmarks[0].x,
          );
          const thumbCos = Math.cos(thumbAngle);
          // thumbCos > threshold = thumb pointing raw-right = screen-left → ArrowLeft
          // thumbCos < -threshold = thumb pointing raw-left = screen-right → ArrowRight
          // Between: ambiguous — release keys (handled below via wantedKey === null)
          const wantedKey =
            thumbCos > THUMB_COS_THRESHOLD
              ? 'ArrowLeft'
              : thumbCos < -THUMB_COS_THRESHOLD
                ? 'ArrowRight'
                : null;

          gestureStateRef.current = {
            smoothedCenter,
            smoothedHandScale,
            peaceZoomActive: false,
            activeGesture: 'pan',
          };

          const trackedHandLabel = describeTrackedHand(trackedHand);

          {
            const heldKey = thumbKeyRef.current;
            if (heldKey !== wantedKey) {
              if (heldKey) {
                window.dispatchEvent(new KeyboardEvent('keyup', { code: heldKey, bubbles: true }));
                iframeRef.current?.contentWindow?.postMessage({ type: 'splat-keyup', code: heldKey }, '*');
              }
              if (wantedKey) {
                window.dispatchEvent(new KeyboardEvent('keydown', { code: wantedKey, bubbles: true }));
                iframeRef.current?.contentWindow?.postMessage({ type: 'splat-keydown', code: wantedKey }, '*');
              }
              thumbKeyRef.current = wantedKey;
            }
            updateHandStatus(
              'tracking',
              wantedKey
                ? `Tracking ${trackedHandLabel}. Thumb ${wantedKey === 'ArrowLeft' ? '←' : '→'}: moving.`
                : `Tracking ${trackedHandLabel}. Point thumb left or right to move.`,
            );
          }

          animationFrameId = window.requestAnimationFrame(step);
        };

        animationFrameId = window.requestAnimationFrame(step);
      } catch (error) {
        if (isDisposed) return;

        resetGestureState();
        clearOverlay();
        const message =
          error instanceof DOMException && error.name === 'NotAllowedError'
            ? 'Camera permission denied'
            : error instanceof Error
              ? error.message
              : 'Unable to initialize hand tracking';
        updateHandStatus(
          error instanceof DOMException && error.name === 'NotAllowedError'
            ? 'permission-denied'
            : 'error',
          message,
        );
      }
    };

    void boot();

    return () => {
      isDisposed = true;
      window.cancelAnimationFrame(animationFrameId);
      resetGestureState();
      drawingUtils?.close();
      handLandmarker?.close();
      if (stream) {
        for (const track of stream.getTracks()) {
          track.stop();
        }
      }
      if (videoElement) {
        videoElement.pause();
        videoElement.srcObject = null;
      }
      clearOverlay();
      if (handControlEnabled) {
        updateHandStatus('inactive', 'Hand control off');
      }
    };
  }, [handControlEnabled, usePlyRenderer, viewerState]);

  const zoomFromIframe = useRef(false);
  const zoomInitialized = useRef(false);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'splat-camera-pos') {
        setCamPos({ x: e.data.x, y: e.data.y, z: e.data.z });
      }
      if (e.data?.type === 'splat-zoom') {
        if (!zoomInitialized.current) {
          // First ping from iframe — push our desired initial zoom back
          zoomInitialized.current = true;
          iframeRef.current?.contentWindow?.postMessage(
            { type: 'splat-set-zoom', value: camDistRef.current },
            '*',
          );
        } else {
          zoomFromIframe.current = true;
          setCamDist(e.data.value);
          zoomFromIframe.current = false;
        }
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  const applySplatRotation = (rx: number, ry: number, rz: number) => {
    const win = iframeRef.current?.contentWindow;
    sendSplatGesture(win, { type: 'splat-hand-control', action: 'reset' });
    sendSplatGesture(win, { type: 'splat-hand-control', action: 'orbit', dx: ry, dy: rx });
    sendSplatGesture(win, { type: 'splat-hand-control', action: 'roll', delta: rz });
  };

  const initialRotApplied = useRef(false);
  useEffect(() => {
    if (usePlyRenderer) {
      initialRotApplied.current = false;
      return;
    }
    // Splat iframe manages its own camera via COLMAP trajectory — skip rotation gestures
    initialRotApplied.current = true;
  }, [usePlyRenderer]);

  useEffect(() => {
    if (usePlyRenderer && pointsRef.current) {
      pointsRef.current.rotation.set(rotX, rotY, rotZ);
      const lb = localBBoxRef.current;
      if (lb) floodCalibrationRef.current = computeWorldYBounds(lb, rotX, rotY, rotZ);
    }
  }, [rotX, rotY, rotZ, usePlyRenderer]);

  const prevCamRef = useRef({ elev: 0.238, dist: 0.359 });

  useEffect(() => {
    if (usePlyRenderer) {
      camElevRef.current = camElev;
      camDistRef.current = camDist;
      fitCameraRef.current?.();
    } else {
      const dElev = camElev - prevCamRef.current.elev;
      prevCamRef.current = { elev: camElev, dist: camDist };
      if (Math.abs(dElev) > 0.001) {
        sendSplatGesture(iframeRef.current?.contentWindow, {
          type: 'splat-hand-control', action: 'orbit', dx: 0, dy: -dElev * 0.8,
        });
      }
      if (!zoomFromIframe.current) {
        iframeRef.current?.contentWindow?.postMessage(
          { type: 'splat-set-zoom', value: camDist },
          '*',
        );
      }
    }
  }, [camElev, camDist, usePlyRenderer]);

  return (
    <div
      className="splat-wrap"
      aria-label={usePlyRenderer ? '3D PLY viewer' : '3D Gaussian Splat Viewer'}
      style={{ background: '#020a12' }}
    >
      {usePlyRenderer ? (
        <>
          <div
            ref={canvasHostRef}
            style={{
              position: 'absolute',
              inset: 0,
            }}
          />
          {hazardTooltip ? (
            <div
              role="tooltip"
              style={{
                position: 'absolute',
                left: Math.min(hazardTooltip.x + 14, (canvasHostRef.current?.clientWidth ?? 0) - 280),
                top: Math.max(hazardTooltip.y - 12, 8),
                zIndex: 25,
                maxWidth: 280,
                padding: '10px 12px',
                background: 'rgba(3, 12, 22, 0.92)',
                border: `1px solid ${HAZARD_LABEL_COLOR[hazardTooltip.hazard.label] ?? 'rgba(0, 212, 180, 0.35)'}`,
                color: '#e2f1ff',
                fontFamily: 'var(--font-body)',
                fontSize: 12,
                lineHeight: 1.4,
                pointerEvents: 'none',
                backdropFilter: 'blur(12px)',
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                  color: HAZARD_LABEL_COLOR[hazardTooltip.hazard.label] ?? 'var(--accent)',
                  marginBottom: 4,
                }}
              >
                {hazardTooltip.hazard.id} · {hazardTooltip.hazard.label.replace(/_/g, ' ')}
              </div>
              <div style={{ marginBottom: 6 }}>{hazardTooltip.hazard.summary}</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-mid)' }}>
                severity {(hazardTooltip.hazard.severity * 100).toFixed(0)}% · confidence: geometric proxy
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <iframe
          ref={iframeRef}
          src={splatIframeSrc}
          style={{ border: 'none', width: '100%', height: '100%', display: 'block' }}
          title="3D Gaussian Splat Viewer"
        />
      )}
      <div
        style={{
          position: 'absolute',
          top: 18,
          left: 18,
          zIndex: 20,
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          alignItems: 'flex-start',
        }}
      >
        <div
          role="button"
          tabIndex={0}
          onClick={() => viewerState === 'ready' && setHandControlEnabled((v) => !v)}
          onKeyDown={(e) => e.key === 'Enter' && viewerState === 'ready' && setHandControlEnabled((v) => !v)}
          style={{
            display: 'grid',
            gap: 8,
            minWidth: 220,
            padding: '10px 12px',
            background: 'rgba(3, 12, 22, 0.82)',
            border: `1px solid ${
              handControlEnabled ? 'rgba(0, 212, 180, 0.4)' : 'rgba(0, 212, 180, 0.16)'
            }`,
            backdropFilter: 'blur(12px)',
            cursor: viewerState === 'ready' ? 'pointer' : 'default',
            opacity: viewerState === 'ready' ? 1 : 0.55,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color:
                handStatus === 'tracking'
                  ? 'var(--accent)'
                  : handStatus === 'error' || handStatus === 'permission-denied'
                    ? '#fca5a5'
                    : 'var(--text-mid)',
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background:
                  handStatus === 'tracking'
                    ? 'var(--accent)'
                    : handStatus === 'error' || handStatus === 'permission-denied'
                      ? '#ef4444'
                      : 'rgba(108, 180, 204, 0.7)',
                boxShadow:
                  handStatus === 'tracking'
                    ? '0 0 12px rgba(0, 212, 180, 0.65)'
                    : 'none',
              }}
            />
            {handStatus === 'inactive' ? 'Hand Control Off' : handStatus.replace('-', ' ')}
          </div>
          {handControlEnabled ? (
            <div
              style={{
                position: 'relative',
                width: 220,
                aspectRatio: '4 / 3',
                overflow: 'hidden',
                border: '1px solid rgba(0, 212, 180, 0.2)',
                background:
                  'linear-gradient(180deg, rgba(5, 18, 31, 0.94), rgba(2, 10, 18, 0.94))',
              }}
            >
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                style={{
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                  transform: 'scaleX(-1)',
                  opacity: handStatus === 'permission-denied' ? 0.2 : 0.92,
                }}
              />
              <canvas
                ref={videoOverlayRef}
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: '100%',
                  height: '100%',
                  transform: 'scaleX(-1)',
                  pointerEvents: 'none',
                }}
              />
              {handStatus === 'permission-denied' ? (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    display: 'grid',
                    placeItems: 'center',
                    padding: 18,
                    textAlign: 'center',
                    fontFamily: 'var(--font-body)',
                    fontSize: '12px',
                    lineHeight: 1.45,
                    color: '#fca5a5',
                    background: 'rgba(2, 10, 18, 0.82)',
                  }}
                >
                  Camera permission denied. Allow webcam access to use hand control.
                </div>
              ) : null}
            </div>
          ) : null}
          {handControlEnabled ? (
            <div
              style={{
                display: 'grid',
                gap: 4,
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: 'rgba(173, 224, 235, 0.74)',
              }}
            >
              <div>Move hand left/right: Pan</div>
              <div>Works with either hand</div>
            </div>
          ) : null}
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 18,
          bottom: 18,
          zIndex: 22,
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          alignItems: 'flex-start',
          maxWidth: 'min(320px, calc(100vw - 36px))',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
        }}
      >
        {camPos && !usePlyRenderer ? (
          <div
            style={{
              fontSize: '11px',
              letterSpacing: '0.12em',
              background: 'rgba(3,12,22,0.75)',
              border: '1px solid rgba(0,212,180,0.18)',
              padding: '8px 12px',
              lineHeight: 1.8,
              pointerEvents: 'none',
            }}
          >
            <div style={{ color: 'rgba(94,142,173,0.7)', textTransform: 'uppercase', fontSize: '9px', marginBottom: 2 }}>Position</div>
            <div><span style={{ color: 'var(--text-mid)' }}>X</span> <span style={{ color: 'var(--accent)' }}>{camPos.x.toFixed(3)}</span></div>
            <div><span style={{ color: 'var(--text-mid)' }}>Y</span> <span style={{ color: 'var(--accent)' }}>{camPos.y.toFixed(3)}</span></div>
            <div><span style={{ color: 'var(--text-mid)' }}>Z</span> <span style={{ color: 'var(--accent)' }}>{camPos.z.toFixed(3)}</span></div>
          </div>
        ) : null}
        <div>
          <button
            type="button"
            onClick={() => setShowSetup(s => !s)}
            style={{
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--text-hi)',
              background: 'rgba(3,12,22,0.82)',
              border: '1px solid rgba(0,212,180,0.28)',
              padding: '8px 12px',
              cursor: 'pointer',
              marginBottom: showSetup ? 8 : 0,
              display: 'block',
            }}
          >
            {showSetup ? 'Hide Setup' : 'Camera Setup'}
          </button>
          {showSetup ? (
          <div
            style={{
              background: 'rgba(3,12,22,0.90)',
              border: '1px solid rgba(0,212,180,0.22)',
              backdropFilter: 'blur(12px)',
              padding: '14px 16px',
              display: 'grid',
              gap: 10,
              minWidth: 260,
            }}
          >
            {([
              ['Rot X', rotX, setRotX, -Math.PI, Math.PI],
              ['Rot Y', rotY, setRotY, -Math.PI, Math.PI],
              ['Rot Z', rotZ, setRotZ, -Math.PI, Math.PI],
              ['Cam Elev', camElev, setCamElev, -1, 1.5],
              ['Cam Dist', camDist, setCamDist, -1.5, 3],
            ] as const).map(([label, value, setter, min, max]) => (
              <label key={label} style={{ display: 'grid', gap: 4 }}>
                <span
                  style={{
                    color: 'var(--text-mid)',
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    fontSize: '10px',
                  }}
                >
                  {label}:{' '}
                  <span style={{ color: 'var(--accent)' }}>
                    {(value as number).toFixed(3)}
                  </span>
                </span>
                <input
                  type="range"
                  min={min as number}
                  max={max as number}
                  step={0.001}
                  value={value as number}
                  onChange={e =>
                    (setter as (v: number) => void)(parseFloat(e.target.value))
                  }
                  style={{ width: '100%', accentColor: 'var(--accent)' }}
                />
              </label>
            ))}
            <button
              type="button"
              onClick={() => {
                setRotX(-1.297);
                setRotY(-0.122);
                setRotZ(0.320);
                setCamElev(0.238);
                setCamDist(0.359);
              }}
              style={{
                marginTop: 4,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                color: 'var(--text-mid)',
                background: 'transparent',
                border: '1px solid rgba(0,212,180,0.18)',
                padding: '6px 10px',
                cursor: 'pointer',
                fontSize: '10px',
              }}
            >
              Reset
            </button>
            <div
              style={{
                color: 'rgba(94,142,173,0.6)',
                fontSize: '10px',
                lineHeight: 1.5,
                marginTop: 2,
              }}
            >
              Values to hardcode:
              <br />
              rotX={rotX.toFixed(3)} rotY={rotY.toFixed(3)} rotZ={rotZ.toFixed(3)}
              <br />
              elev={camElev.toFixed(3)} dist={camDist.toFixed(3)}
            </div>
          </div>
        ) : null}
        </div>
      </div>
      {viewerState === 'loading' ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            letterSpacing: '0.18em',
            color: 'rgba(94, 142, 173, 0.78)',
            textTransform: 'uppercase',
            pointerEvents: 'none',
            background: 'linear-gradient(180deg, rgba(2,10,18,0.2), rgba(2,10,18,0.85))',
          }}
        >
          Loading {usePlyRenderer ? 'PLY scene' : 'Gaussian splat'}
        </div>
      ) : null}
      {viewerState === 'error' ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'grid',
            placeItems: 'center',
            padding: 24,
            textAlign: 'center',
            background: 'linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.96))',
            color: '#fca5a5',
            fontFamily: 'var(--font-body)',
            zIndex: 30,
          }}
        >
          <div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                marginBottom: 10,
                color: 'rgba(252, 165, 165, 0.82)',
              }}
            >
              Viewer Error
            </div>
            <div style={{ fontSize: '14px', lineHeight: 1.6 }}>
              {errorMessage ?? 'Unable to load 3D scene.'}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
});

export default SplatViewer;
