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

import {
  buildEulerRotationMatrices,
  computeFloodVolumeFromLocalBox,
  lerp,
} from '@/lib/flood';
import type { FloodVolume } from '@/lib/flood';
import type { FloodCalibration, SceneHotspot } from '@/lib/locations';
import type { CameraPose, ViewerCommandApi, ViewerState } from '@/lib/viewer-types';
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

function handStatusShortLabel(status: HandStatus): string {
  switch (status) {
    case 'inactive':
      return 'Off';
    case 'initializing':
      return 'Starting';
    case 'requesting-camera':
      return 'Camera';
    case 'no-hand':
      return 'Ready';
    case 'tracking':
      return 'Live';
    case 'permission-denied':
      return 'Blocked';
    case 'error':
      return 'Error';
    default:
      return 'Hand';
  }
}

type Point2 = { x: number; y: number };
type DetectedHand = 'left' | 'right' | 'unknown';
type GestureMode = 'orbit' | 'zoom' | 'pan' | 'roll';
type GestureState = {
  smoothedCenter: Point2 | null;
  smoothedPinch: number | null;
  smoothedHandScale: number | null;
  smoothedRollAngle: number | null;
  pinchZoomActive: boolean;
  activeGesture: GestureMode | null;
  steadyOpenPalmStartMs: number | null;
  resetLatched: boolean;
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
type FloodShader = {
  uniforms: {
    uFloodLevelY: { value: number };
    uFloodBandWidth: { value: number };
    uFloodEdgeSoftness: { value: number };
    uFloodTintStrength: { value: number };
    uFloodColor: { value: import('three').Color };
    uFloodBoundsMinXZ: { value: import('three').Vector2 };
    uFloodBoundsMaxXZ: { value: import('three').Vector2 };
    uFloodReach: { value: number };
    uFloodProgress: { value: number };
    uTime: { value: number };
  };
};
const HAND_LANDMARKER_MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
const HAND_LANDMARKER_WASM_URL =
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.34/wasm';
const PALM_INDICES = [0, 5, 9, 13, 17] as const;
const GESTURE_SMOOTHING = 0.35;
const ORBIT_DEADZONE = 0.003;
const PAN_DEADZONE = 0.0024;
const SCALE_ZOOM_DEADZONE = 0.0025;
const ROLL_DEADZONE = 0.025;
const PINCH_ENTER_THRESHOLD = 0.11;
const PINCH_EXIT_THRESHOLD = 0.18;
const OPEN_PALM_RESET_HOLD_MS = 1200;
const OPEN_PALM_RESET_DEADZONE = 0.0014;

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
function postSplatFlood(
  targetWindow: Window | null | undefined,
  progress: number,
  calibration: FloodCalibration | undefined,
  rx: number,
  ry: number,
  rz: number,
) {
  if (!targetWindow) return;
  const { rotationMatrix, inverseRotationMatrix } = buildEulerRotationMatrices(rx, ry, rz);

  targetWindow.postMessage(
    {
      type: 'splat-flood',
      progress,
      startY: calibration?.startY,
      endY: calibration?.endY,
      minX: calibration?.minX,
      maxX: calibration?.maxX,
      minZ: calibration?.minZ,
      maxZ: calibration?.maxZ,
      rotationMatrix,
      inverseRotationMatrix,
    },
    location.origin,
  );
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
};

type SplatViewerProps = {
  splatUrl: string;
  renderer?: 'auto' | 'ply' | 'splat';
  floodProgress?: number;
  floodCalibration?: FloodCalibration;
  hotspots?: SceneHotspot[];
  onViewerStateChange?: (state: ViewerState) => void;
};

const SplatViewer = forwardRef<ViewerCommandApi, SplatViewerProps>(function SplatViewer(
  {
    splatUrl,
    renderer = 'auto',
    floodProgress = 0,
    floodCalibration: propFloodCalibration,
    hotspots = [],
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
  const floodCalibrationRef = useRef<FloodVolume | null>(null);
  const localBBoxRef = useRef<{ min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } } | null>(null);
  const floodProgressRef = useRef(clamp(floodProgress, 0, 1));
  const pointsRef = useRef<import('three').Points | null>(null);
  const fitCameraRef = useRef<(() => void) | null>(null);

  const [rotX, setRotX] = useState(-1.327);
  const [rotY, setRotY] = useState(0.640);
  const [rotZ, setRotZ] = useState(0.030);
  const [camElev, setCamElev] = useState(0.238);
  const [camDist, setCamDist] = useState(1.350);
  const [showSetup, setShowSetup] = useState(false);
  const [camPos, setCamPos] = useState<{ x: number; y: number; z: number } | null>(null);
  const camElevRef = useRef(0.238);
  const camDistRef = useRef(1.350);
  const rotRef = useRef({ x: -1.327, y: 0.640, z: 0.030 });
  const gestureStateRef = useRef<GestureState>({
    smoothedCenter: null,
    smoothedPinch: null,
    smoothedHandScale: null,
    smoothedRollAngle: null,
    pinchZoomActive: false,
    activeGesture: null,
    steadyOpenPalmStartMs: null,
    resetLatched: false,
  });
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
  const [handStatusDetail, setHandStatusDetail] = useState('Hand control off');

  const splatIframeSrc = useMemo(
    () => `/splat/viewer.html?url=${encodeURIComponent(splatUrl)}`,
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
    }),
    [],
  );

  useEffect(() => {
    onViewerStateChange?.(viewerState);
  }, [onViewerStateChange, viewerState]);

  useEffect(() => {
    floodProgressRef.current = clampedFloodProgress;

    // Handle PLY renderer flood update
    const floodShader = floodShaderRef.current;
    const floodCalibration = floodCalibrationRef.current;
    if (floodShader && floodCalibration) {
      floodShader.uniforms.uFloodLevelY.value = lerp(
        floodCalibration.startY,
        floodCalibration.endY,
        clampedFloodProgress,
      );
      floodShader.uniforms.uFloodBoundsMinXZ.value.set(
        floodCalibration.minX,
        floodCalibration.minZ,
      );
      floodShader.uniforms.uFloodBoundsMaxXZ.value.set(
        floodCalibration.maxX,
        floodCalibration.maxZ,
      );
      floodShader.uniforms.uFloodReach.value =
        floodCalibration.maxEdgeDistance * clampedFloodProgress;
      floodShader.uniforms.uFloodProgress.value = clampedFloodProgress;
    }
    // Handle splat iframe flood update
    if (!usePlyRenderer) {
      const splatWindow = iframeRef.current?.contentWindow;
      postSplatFlood(
        splatWindow,
        clampedFloodProgress,
        propFloodCalibration,
        rotX,
        rotY,
        rotZ,
      );
    }
  }, [clampedFloodProgress, usePlyRenderer, propFloodCalibration, rotX, rotY, rotZ]);

  useEffect(() => {
    rotRef.current = { x: rotX, y: rotY, z: rotZ };
  }, [rotX, rotY, rotZ]);

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
        const { x: currentRotX, y: currentRotY, z: currentRotZ } = rotRef.current;
        const floodCalibration = computeFloodVolumeFromLocalBox(
          localBox,
          currentRotX,
          currentRotY,
          currentRotZ,
          propFloodCalibration,
        );
        floodCalibrationRef.current = floodCalibration;
        const initialFloodLevelY = lerp(
          floodCalibration.startY,
          floodCalibration.endY,
          floodProgressRef.current,
        );
        const initialFloodReach = floodCalibration.maxEdgeDistance * floodProgressRef.current;

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
          shader.uniforms.uFloodBoundsMinXZ = {
            value: new THREE.Vector2(floodCalibration.minX, floodCalibration.minZ),
          };
          shader.uniforms.uFloodBoundsMaxXZ = {
            value: new THREE.Vector2(floodCalibration.maxX, floodCalibration.maxZ),
          };
          shader.uniforms.uFloodReach = { value: initialFloodReach };
          shader.uniforms.uFloodProgress = { value: floodProgressRef.current };
          shader.uniforms.uTime = { value: performance.now() / 1000 };

          shader.vertexShader = `
            varying vec3 vWorldPos;
          ${shader.vertexShader}`.replace(
            '#include <begin_vertex>',
            `#include <begin_vertex>
            vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;`,
          );

          shader.fragmentShader = `
            uniform float uFloodLevelY;
            uniform float uFloodBandWidth;
            uniform float uFloodEdgeSoftness;
            uniform float uFloodTintStrength;
            uniform vec3 uFloodColor;
            uniform vec2 uFloodBoundsMinXZ;
            uniform vec2 uFloodBoundsMaxXZ;
            uniform float uFloodReach;
            uniform float uFloodProgress;
            uniform float uTime;
            varying vec3 vWorldPos;
          ${shader.fragmentShader}`.replace(
            '#include <color_fragment>',
            `#include <color_fragment>
            float heightSubmerged = smoothstep(
              uFloodLevelY + uFloodEdgeSoftness,
              uFloodLevelY - uFloodEdgeSoftness,
              vWorldPos.y
            );

            float waterlineBand = 1.0 - smoothstep(
              0.0,
              uFloodBandWidth,
              abs(vWorldPos.y - uFloodLevelY)
            );

            float band = waterlineBand;

            float pulse = 0.88 + 0.12 * sin(
              uTime * 1.6 + vWorldPos.x * 2.2 + vWorldPos.z * 1.8
            );

            diffuseColor.rgb = mix(
              diffuseColor.rgb,
              uFloodColor,
              heightSubmerged * uFloodTintStrength
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
            floodShader.uniforms.uFloodBoundsMinXZ.value.set(
              activeFloodCalibration.minX,
              activeFloodCalibration.minZ,
            );
            floodShader.uniforms.uFloodBoundsMaxXZ.value.set(
              activeFloodCalibration.maxX,
              activeFloodCalibration.maxZ,
            );
            floodShader.uniforms.uFloodReach.value =
              activeFloodCalibration.maxEdgeDistance * floodProgressRef.current;
            floodShader.uniforms.uFloodProgress.value = floodProgressRef.current;
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
  }, [hotspotMap, propFloodCalibration, splatUrl, usePlyRenderer]);

  useEffect(() => {
    if (!handControlEnabled || viewerState !== 'ready') return;

    const videoElement = videoRef.current;
    let isDisposed = false;
    let animationFrameId = 0;
    let stream: MediaStream | null = null;
    let handLandmarker: import('@mediapipe/tasks-vision').HandLandmarker | null = null;
    let drawingUtils: import('@mediapipe/tasks-vision').DrawingUtils | null = null;

    const resetGestureState = () => {
      gestureStateRef.current = {
        smoothedCenter: null,
        smoothedPinch: null,
        smoothedHandScale: null,
        smoothedRollAngle: null,
        pinchZoomActive: false,
        activeGesture: null,
        steadyOpenPalmStartMs: null,
        resetLatched: false,
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
          'Show your right hand. Open hand orbits, pinch zooms, fist pans, V-sign rolls.',
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
              'Show your right hand. Open hand orbits, pinch zooms, fist pans, V-sign rolls.',
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
              'Show your right hand. Open hand orbits, pinch zooms, fist pans, V-sign rolls.',
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
          const pinchDistance = Math.hypot(
            landmarks[4].x - landmarks[8].x,
            landmarks[4].y - landmarks[8].y,
          );
          const handScale =
            (
              Math.hypot(
                landmarks[0].x - landmarks[5].x,
                landmarks[0].y - landmarks[5].y,
              ) +
              Math.hypot(
                landmarks[0].x - landmarks[9].x,
                landmarks[0].y - landmarks[9].y,
              ) +
              Math.hypot(
                landmarks[0].x - landmarks[17].x,
                landmarks[0].y - landmarks[17].y,
              )
            ) / 3;
          const fingerState = getExtendedFingers(landmarks);
          const extendedFingerCount = Object.values(fingerState).filter(Boolean).length;
          const peaceSignActive =
            fingerState.index &&
            fingerState.middle &&
            !fingerState.ring &&
            !fingerState.pinky;
          const fistActive = extendedFingerCount <= 1;
          const rollAngle = Math.atan2(
            landmarks[12].y - landmarks[8].y,
            landmarks[12].x - landmarks[8].x,
          );

          const smoothedCenter = gestureStateRef.current.smoothedCenter
            ? {
                x:
                  gestureStateRef.current.smoothedCenter.x +
                  (palmCenter.x - gestureStateRef.current.smoothedCenter.x) *
                    GESTURE_SMOOTHING,
                y:
                  gestureStateRef.current.smoothedCenter.y +
                  (palmCenter.y - gestureStateRef.current.smoothedCenter.y) *
                    GESTURE_SMOOTHING,
              }
            : palmCenter;
          const smoothedPinch =
            gestureStateRef.current.smoothedPinch === null
              ? pinchDistance
              : gestureStateRef.current.smoothedPinch +
                (pinchDistance - gestureStateRef.current.smoothedPinch) *
                  GESTURE_SMOOTHING;
          const smoothedHandScale =
            gestureStateRef.current.smoothedHandScale === null
              ? handScale
              : gestureStateRef.current.smoothedHandScale +
                (handScale - gestureStateRef.current.smoothedHandScale) *
                  GESTURE_SMOOTHING;
          const smoothedRollAngle =
            gestureStateRef.current.smoothedRollAngle === null
              ? rollAngle
              : gestureStateRef.current.smoothedRollAngle +
                normalizeAngleDelta(rollAngle - gestureStateRef.current.smoothedRollAngle) *
                  GESTURE_SMOOTHING;

          const prevCenter = gestureStateRef.current.smoothedCenter;
          const prevHandScale = gestureStateRef.current.smoothedHandScale;
          const prevRollAngle = gestureStateRef.current.smoothedRollAngle;
          const wasPinchZoomActive = gestureStateRef.current.pinchZoomActive;
          const pinchZoomActive = wasPinchZoomActive
            ? smoothedPinch < PINCH_EXIT_THRESHOLD
            : smoothedPinch < PINCH_ENTER_THRESHOLD;
          const nextGesture: GestureMode = pinchZoomActive
            ? 'zoom'
            : peaceSignActive
              ? 'roll'
              : fistActive
                ? 'pan'
                : 'orbit';
          const previousGesture = gestureStateRef.current.activeGesture;
          const gestureChanged = previousGesture !== nextGesture;
          const centerDelta = prevCenter ? distance2D(smoothedCenter, prevCenter) : 0;
          let steadyOpenPalmStartMs = gestureStateRef.current.steadyOpenPalmStartMs;
          let resetLatched = gestureStateRef.current.resetLatched;

          if (nextGesture !== 'orbit' || centerDelta > OPEN_PALM_RESET_DEADZONE) {
            steadyOpenPalmStartMs = null;
            resetLatched = false;
          } else if (steadyOpenPalmStartMs === null || gestureChanged) {
            steadyOpenPalmStartMs = performance.now();
          }

          gestureStateRef.current = {
            smoothedCenter,
            smoothedPinch,
            smoothedHandScale,
            smoothedRollAngle,
            pinchZoomActive,
            activeGesture: nextGesture,
            steadyOpenPalmStartMs,
            resetLatched,
          };

          const trackedHandLabel = describeTrackedHand(trackedHand);

          if (
            nextGesture === 'orbit' &&
            steadyOpenPalmStartMs !== null &&
            !resetLatched &&
            performance.now() - steadyOpenPalmStartMs >= OPEN_PALM_RESET_HOLD_MS
          ) {
            if (usePlyRenderer && controls) {
              resetOrbitCamera(controls, resetCameraRef.current);
            } else {
              sendSplatGesture(splatWindow, {
                type: 'splat-hand-control',
                action: 'reset',
              });
            }
            gestureStateRef.current.resetLatched = true;
            updateHandStatus(
              'tracking',
              `Tracking ${trackedHandLabel}. Open palm hold reset the view.`,
            );
          } else if (nextGesture === 'zoom' && !gestureChanged && prevHandScale !== null) {
            const scaleDelta = smoothedHandScale - prevHandScale;
            if (Math.abs(scaleDelta) > SCALE_ZOOM_DEADZONE) {
              if (usePlyRenderer && controls) {
                const zoomScale = 1 + clamp(Math.abs(scaleDelta) * 18, 0.04, 0.28);
                if (scaleDelta > 0) {
                  controls.dollyIn(zoomScale);
                } else {
                  controls.dollyOut(zoomScale);
                }
                controls.update();
              } else {
                const zoomDelta = clamp(scaleDelta * 12, -0.48, 0.48);
                sendSplatGesture(splatWindow, {
                  type: 'splat-hand-control',
                  action: 'zoom',
                  delta: zoomDelta,
                });
              }
            }
            updateHandStatus(
              'tracking',
              `Tracking ${trackedHandLabel}. Pinch and move closer to zoom in, farther to zoom out.`,
            );
          } else if (nextGesture === 'roll' && !gestureChanged && prevRollAngle !== null) {
            const rollDelta = normalizeAngleDelta(smoothedRollAngle - prevRollAngle);
            if (Math.abs(rollDelta) > ROLL_DEADZONE) {
              if (usePlyRenderer && controls) {
                rollOrbitCamera(controls, clamp(rollDelta * 0.9, -0.14, 0.14));
              } else {
                sendSplatGesture(splatWindow, {
                  type: 'splat-hand-control',
                  action: 'roll',
                  delta: clamp(rollDelta * 1.3, -0.18, 0.18),
                });
              }
            }
            updateHandStatus(
              'tracking',
              `Tracking ${trackedHandLabel}. V-sign twist rolls the camera.`,
            );
          } else if (nextGesture === 'pan' && !gestureChanged && prevCenter) {
            const deltaX = smoothedCenter.x - prevCenter.x;
            const deltaY = smoothedCenter.y - prevCenter.y;

            if (
              Math.abs(deltaX) > PAN_DEADZONE ||
              Math.abs(deltaY) > PAN_DEADZONE
            ) {
              if (usePlyRenderer && controls) {
                panOrbitCamera(
                  controls,
                  clamp(deltaX * 2.3, -0.18, 0.18),
                  clamp(deltaY * 2.3, -0.18, 0.18),
                );
              } else {
                sendSplatGesture(splatWindow, {
                  type: 'splat-hand-control',
                  action: 'pan',
                  dx: clamp(deltaX * 0.92, -0.12, 0.12),
                  dy: clamp(deltaY * 0.92, -0.12, 0.12),
                });
              }
            }
            updateHandStatus(
              'tracking',
              `Tracking ${trackedHandLabel}. Close your hand into a fist and drag to pan.`,
            );
          } else if (prevCenter && nextGesture === 'orbit') {
            const deltaX = smoothedCenter.x - prevCenter.x;
            const deltaY = smoothedCenter.y - prevCenter.y;

            if (
              Math.abs(deltaX) > ORBIT_DEADZONE ||
              Math.abs(deltaY) > ORBIT_DEADZONE
            ) {
              const orbitX = clamp(deltaX * Math.PI * 2.4, -0.18, 0.18);
              const orbitY = clamp(deltaY * Math.PI * 2.1, -0.16, 0.16);
              if (usePlyRenderer && controls) {
                controls.rotateLeft(orbitX);
                controls.rotateUp(orbitY);
                controls.update();
              } else {
                sendSplatGesture(splatWindow, {
                  type: 'splat-hand-control',
                  action: 'orbit',
                  dx: orbitX * 1.8,
                  dy: orbitY * 1.8,
                });
              }
            }
            const resetCountdownSeconds =
              steadyOpenPalmStartMs === null
                ? null
                : Math.max(
                    0,
                    (OPEN_PALM_RESET_HOLD_MS - (performance.now() - steadyOpenPalmStartMs)) /
                      1000,
                  );
            updateHandStatus(
              'tracking',
              resetCountdownSeconds !== null && centerDelta <= OPEN_PALM_RESET_DEADZONE
                ? `Tracking ${trackedHandLabel}. Open hand orbits. Hold steady ${resetCountdownSeconds.toFixed(1)}s to reset.`
                : `Tracking ${trackedHandLabel}. Open hand orbits, pinch zooms, fist pans, V-sign rolls.`,
            );
          } else {
            updateHandStatus(
              'tracking',
              `Tracking ${trackedHandLabel}. Open hand orbits, pinch zooms, fist pans, V-sign rolls.`,
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

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'splat-camera-pos') {
        setCamPos({ x: e.data.x, y: e.data.y, z: e.data.z });
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

    if (!initialRotApplied.current && viewerState === 'ready') {
      initialRotApplied.current = true;
      applySplatRotation(rotX, rotY, rotZ);
    }
  }, [usePlyRenderer, viewerState, rotX, rotY, rotZ]);

  useEffect(() => {
    if (usePlyRenderer) {
      if (pointsRef.current) {
        pointsRef.current.rotation.set(rotX, rotY, rotZ);
        const lb = localBBoxRef.current;
        if (lb) {
          floodCalibrationRef.current = computeFloodVolumeFromLocalBox(
            lb,
            rotX,
            rotY,
            rotZ,
            propFloodCalibration,
          );
        }
      }
    } else if (initialRotApplied.current) {
      applySplatRotation(rotX, rotY, rotZ);
    }
  }, [propFloodCalibration, rotX, rotY, rotZ, usePlyRenderer]);

  const prevCamRef = useRef({ elev: 0.238, dist: 1.350 });

  useEffect(() => {
    if (usePlyRenderer) {
      camElevRef.current = camElev;
      camDistRef.current = camDist;
      fitCameraRef.current?.();
    } else {
      const dElev = camElev - prevCamRef.current.elev;
      const dDist = camDist - prevCamRef.current.dist;
      prevCamRef.current = { elev: camElev, dist: camDist };
      if (Math.abs(dElev) > 0.001) {
        sendSplatGesture(iframeRef.current?.contentWindow, {
          type: 'splat-hand-control', action: 'orbit', dx: 0, dy: -dElev * 0.8,
        });
      }
      if (Math.abs(dDist) > 0.001) {
        sendSplatGesture(iframeRef.current?.contentWindow, {
          type: 'splat-hand-control', action: 'zoom', delta: dDist * 0.4,
        });
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
        <div
          ref={canvasHostRef}
          style={{
            position: 'absolute',
            inset: 0,
          }}
        />
      ) : (
        <iframe
          ref={iframeRef}
          src={splatIframeSrc}
          onLoad={() => {
            postSplatFlood(
              iframeRef.current?.contentWindow,
              floodProgressRef.current,
              propFloodCalibration,
              rotRef.current.x,
              rotRef.current.y,
              rotRef.current.z,
            );
          }}
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
          gap: 8,
          alignItems: 'flex-start',
        }}
      >
        <div
          style={{
            display: 'grid',
            gap: 6,
            minWidth: 200,
            maxWidth: 'min(280px, calc(100vw - 36px))',
            padding: '8px 10px',
            background: 'rgba(3, 12, 22, 0.82)',
            border: '1px solid rgba(0, 212, 180, 0.16)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                flex: 1,
                minWidth: 0,
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                letterSpacing: '0.14em',
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
                  width: 6,
                  height: 6,
                  flexShrink: 0,
                  borderRadius: '50%',
                  background:
                    handStatus === 'tracking'
                      ? 'var(--accent)'
                      : handStatus === 'error' || handStatus === 'permission-denied'
                        ? '#ef4444'
                        : 'rgba(108, 180, 204, 0.7)',
                  boxShadow:
                    handStatus === 'tracking'
                      ? '0 0 10px rgba(0, 212, 180, 0.65)'
                      : 'none',
                }}
              />
              <span style={{ whiteSpace: 'nowrap' }}>Hand</span>
              <span style={{ opacity: 0.45, padding: '0 2px' }}>·</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {handStatusShortLabel(handStatus)}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setHandControlEnabled((current) => !current)}
              disabled={viewerState !== 'ready'}
              style={{
                flexShrink: 0,
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: handControlEnabled ? '#031018' : 'var(--text-hi)',
                background: handControlEnabled ? 'var(--accent)' : 'rgba(4, 19, 31, 0.92)',
                border: `1px solid ${
                  handControlEnabled ? 'rgba(0, 212, 180, 0.95)' : 'rgba(0, 212, 180, 0.28)'
                }`,
                padding: '6px 10px',
                cursor: viewerState === 'ready' ? 'pointer' : 'default',
                opacity: viewerState === 'ready' ? 1 : 0.55,
                boxShadow: handControlEnabled
                  ? '0 8px 18px rgba(0, 212, 180, 0.14)'
                  : 'none',
              }}
            >
              {handControlEnabled ? 'Off' : 'On'}
            </button>
          </div>
          {handControlEnabled ||
          handStatus === 'error' ||
          handStatus === 'permission-denied' ? (
            <div
              style={{
                fontFamily: 'var(--font-body)',
                fontSize: '11px',
                lineHeight: 1.4,
                color: 'var(--text-mid)',
              }}
            >
              {handStatusDetail}
            </div>
          ) : null}
          {handControlEnabled ? (
            <div
              style={{
                position: 'relative',
                width: '100%',
                maxWidth: 220,
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
                gap: 2,
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                color: 'rgba(173, 224, 235, 0.74)',
              }}
            >
              <div>Open hand: Orbit</div>
              <div>Pinch: Zoom</div>
              <div>Fist drag: Pan</div>
              <div>V-sign twist: Roll</div>
              <div>Open palm hold: Reset</div>
            </div>
          ) : null}
        </div>
      </div>
      {camPos && !usePlyRenderer && (
        <div
          style={{
            position: 'absolute',
            bottom: 18,
            left: 18,
            zIndex: 20,
            fontFamily: 'var(--font-mono)',
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
      )}
      <div
        style={{
          position: 'absolute',
          bottom: 18,
          right: 18,
          zIndex: 20,
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
        }}
      >
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
            marginLeft: 'auto',
          }}
        >
          {showSetup ? 'Hide Setup' : 'Camera Setup'}
        </button>
        {showSetup && (
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
              ['Cam Dist', camDist, setCamDist, 0.5, 3],
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
                setCamDist(1.350);
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
        )}
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
