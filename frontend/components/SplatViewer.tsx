'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { OrbitControls as OrbitControlsType } from 'three/examples/jsm/controls/OrbitControls.js';

type ViewerState = 'loading' | 'ready' | 'error';
type HandStatus =
  | 'inactive'
  | 'initializing'
  | 'requesting-camera'
  | 'tracking'
  | 'no-hand'
  | 'permission-denied'
  | 'error';

type Point2 = { x: number; y: number };
type GestureState = {
  smoothedCenter: Point2 | null;
  smoothedPinch: number | null;
  smoothedHandScale: number | null;
  pinchZoomActive: boolean;
};

const HAND_LANDMARKER_MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
const HAND_LANDMARKER_WASM_URL =
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.34/wasm';
const PALM_INDICES = [0, 5, 9, 13, 17] as const;
const GESTURE_SMOOTHING = 0.35;
const ORBIT_DEADZONE = 0.003;
const SCALE_ZOOM_DEADZONE = 0.0025;
const PINCH_ENTER_THRESHOLD = 0.11;
const PINCH_EXIT_THRESHOLD = 0.18;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function sendSplatGesture(
  targetWindow: Window | null | undefined,
  message:
    | { type: 'splat-hand-control'; action: 'orbit'; dx: number; dy: number }
    | { type: 'splat-hand-control'; action: 'zoom'; delta: number },
) {
  if (!targetWindow) return;

  type SplatControlWindow = Window & {
    __splatHandControl?: {
      orbit?: (dx: number, dy: number) => void;
      zoom?: (delta: number) => void;
    };
  };

  const splatWindow = targetWindow as SplatControlWindow;
  if (message.action === 'orbit') {
    splatWindow.__splatHandControl?.orbit?.(message.dx, message.dy);
  } else {
    splatWindow.__splatHandControl?.zoom?.(message.delta);
  }

  splatWindow.postMessage(message, location.origin);
}

export default function SplatViewer({
  splatUrl,
  renderer = 'auto',
}: {
  splatUrl: string;
  renderer?: 'auto' | 'ply' | 'splat';
}) {
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoOverlayRef = useRef<HTMLCanvasElement>(null);
  const controlsRef = useRef<OrbitControlsType | null>(null);
  const gestureStateRef = useRef<GestureState>({
    smoothedCenter: null,
    smoothedPinch: null,
    smoothedHandScale: null,
    pinchZoomActive: false,
  });
  const handStatusRef = useRef<HandStatus>('inactive');
  const handStatusDetailRef = useRef<string>('Hand control off');
  const isPlyAsset = splatUrl.toLowerCase().endsWith('.ply');
  const usePlyRenderer = renderer === 'ply' || (renderer === 'auto' && isPlyAsset);
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

  useEffect(() => {
    if (!usePlyRenderer) return;

    const canvasHost = canvasHostRef.current;
    if (!canvasHost) return;

    let isDisposed = false;
    let animationFrameId = 0;
    let resizeObserver: ResizeObserver | null = null;

    let renderer: import('three').WebGLRenderer | null = null;
    let controls: OrbitControlsType | null = null;
    let geometryToDispose: import('three').BufferGeometry | null = null;
    let materialToDispose: import('three').Material | null = null;
    let onKeyDown: ((e: KeyboardEvent) => void) | null = null;
    let onKeyUp: ((e: KeyboardEvent) => void) | null = null;

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

        renderer = new THREE.WebGLRenderer({
          antialias: true,
          alpha: false,
          powerPreference: 'high-performance',
        });
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        renderer.domElement.style.width = '100%';
        renderer.domElement.style.height = '100%';
        renderer.domElement.style.display = 'block';

        canvasHost.replaceChildren(renderer.domElement);

        controls = new OrbitControls(camera, renderer.domElement);
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
        materialToDispose = pointsMaterial;

        const points = new THREE.Points(loadedGeometry, pointsMaterial);
        scene.add(points);

        const fitCamera = () => {
          if (!renderer) return;

          const width = Math.max(canvasHost.clientWidth, 1);
          const height = Math.max(canvasHost.clientHeight, 1);

          camera.aspect = width / height;
          camera.near = Math.max(radius / 200, 0.001);
          camera.far = Math.max(radius * 25, 10);
          camera.updateProjectionMatrix();

          const fovRadians = (camera.fov * Math.PI) / 180;
          const distance = (radius / Math.tan(fovRadians / 2)) * 1.35;

          camera.position.set(
            center.x,
            center.y + distance * 0.2,
            center.z + distance,
          );
          controls?.target.copy(center);
          controls?.update();

          renderer.setSize(width, height, false);
          renderer.render(scene, camera);
        };

        fitCamera();
        resizeObserver = new ResizeObserver(fitCamera);
        resizeObserver.observe(canvasHost);

        const MOVE_KEYS = new Set(['KeyW','KeyS','KeyA','KeyD','ArrowUp','ArrowDown','ArrowLeft','ArrowRight']);
        const keysDown = new Set<string>();
        onKeyDown = (e: KeyboardEvent) => {
          if (MOVE_KEYS.has(e.code)) e.preventDefault();
          keysDown.add(e.code);
        };
        onKeyUp = (e: KeyboardEvent) => keysDown.delete(e.code);
        window.addEventListener('keydown', onKeyDown);
        window.addEventListener('keyup', onKeyUp);

        const animate = () => {
          if (isDisposed || !renderer) return;

          if (controls && keysDown.size > 0) {
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

          controls?.update();
          renderer.render(scene, camera);
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
      geometryToDispose?.dispose();
      materialToDispose?.dispose();
      renderer?.dispose();
      canvasHost.replaceChildren();
    };
  }, [splatUrl, usePlyRenderer]);

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
        pinchZoomActive: false,
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
      landmarks: import('@mediapipe/tasks-vision').NormalizedLandmark[] | undefined,
      MediaPipe: typeof import('@mediapipe/tasks-vision'),
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

      if (!landmarks) return;

      drawingUtils ??= new MediaPipe.DrawingUtils(context);
      drawingUtils.drawConnectors(landmarks, MediaPipe.HandLandmarker.HAND_CONNECTIONS, {
        color: 'rgba(0, 212, 180, 0.85)',
        lineWidth: 2,
      });
      drawingUtils.drawLandmarks(landmarks, {
        color: '#d6f0f8',
        fillColor: '#00d4b4',
        lineWidth: 1,
        radius: 3,
      });
    };

    const boot = async () => {
      try {
        if (!window.isSecureContext && location.hostname !== 'localhost') {
          updateHandStatus(
            'error',
            'Webcam access requires HTTPS or localhost.',
          );
          return;
        }
        if (!navigator.mediaDevices?.getUserMedia) {
          updateHandStatus('error', 'This browser does not support webcam access.');
          return;
        }

        updateHandStatus('initializing', 'Loading MediaPipe hand tracking…');
        const MediaPipe = await import('@mediapipe/tasks-vision');
        if (isDisposed) return;

        const vision = await MediaPipe.FilesetResolver.forVisionTasks(
          HAND_LANDMARKER_WASM_URL,
        );
        if (isDisposed) return;

        handLandmarker = await MediaPipe.HandLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: HAND_LANDMARKER_MODEL_URL,
            delegate: 'GPU',
          },
          runningMode: 'VIDEO',
          numHands: 1,
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

        updateHandStatus('no-hand', 'Show one hand to orbit. Pinch to zoom.');

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
          const landmarks = result.landmarks[0];
          drawLandmarks(landmarks, MediaPipe);

          if (!landmarks?.length) {
            resetGestureState();
            updateHandStatus('no-hand', 'Show one hand to orbit. Pinch to zoom.');
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
              Math.hypot(landmarks[0].x - landmarks[5].x, landmarks[0].y - landmarks[5].y) +
              Math.hypot(landmarks[0].x - landmarks[9].x, landmarks[0].y - landmarks[9].y) +
              Math.hypot(landmarks[0].x - landmarks[17].x, landmarks[0].y - landmarks[17].y)
            ) / 3;

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

          const prevCenter = gestureStateRef.current.smoothedCenter;
          const prevHandScale = gestureStateRef.current.smoothedHandScale;
          const wasPinchZoomActive = gestureStateRef.current.pinchZoomActive;
          const pinchZoomActive = wasPinchZoomActive
            ? smoothedPinch < PINCH_EXIT_THRESHOLD
            : smoothedPinch < PINCH_ENTER_THRESHOLD;
          gestureStateRef.current = {
            smoothedCenter,
            smoothedPinch,
            smoothedHandScale,
            pinchZoomActive,
          };

          if (pinchZoomActive && prevHandScale !== null) {
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
                sendSplatGesture(
                  splatWindow,
                  {
                    type: 'splat-hand-control',
                    action: 'zoom',
                    delta: zoomDelta,
                  },
                );
              }
            }
            updateHandStatus(
              'tracking',
              'Pinch held. Move your pinched hand closer to zoom in, farther to zoom out.',
            );
          } else if (prevCenter) {
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
                sendSplatGesture(
                  splatWindow,
                  {
                    type: 'splat-hand-control',
                    action: 'orbit',
                    dx: orbitX * 1.8,
                    dy: orbitY * 1.8,
                  },
                );
              }
            }
            updateHandStatus(
              'tracking',
              'Hand detected. Move to orbit, pinch to zoom.',
            );
          } else {
            updateHandStatus(
              'tracking',
              'Hand detected. Move to orbit, pinch to zoom.',
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
        <button
          type="button"
          onClick={() => setHandControlEnabled(current => !current)}
          disabled={viewerState !== 'ready'}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: handControlEnabled ? '#031018' : 'var(--text-hi)',
            background: handControlEnabled ? 'var(--accent)' : 'rgba(3, 12, 22, 0.82)',
            border: `1px solid ${
              handControlEnabled ? 'rgba(0, 212, 180, 0.95)' : 'rgba(0, 212, 180, 0.28)'
            }`,
            padding: '10px 14px',
            cursor: viewerState === 'ready' ? 'pointer' : 'default',
            opacity: viewerState === 'ready' ? 1 : 0.55,
            boxShadow: handControlEnabled
              ? '0 12px 24px rgba(0, 212, 180, 0.18)'
              : 'none',
          }}
        >
          {handControlEnabled ? 'Disable Hand Control' : 'Enable Hand Control'}
        </button>

        <div
          style={{
            display: 'grid',
            gap: 8,
            minWidth: 220,
            padding: '10px 12px',
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
          <div
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: '12px',
              lineHeight: 1.45,
              color: 'var(--text-mid)',
            }}
          >
            {handStatusDetail}
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
                }}
              />
            </div>
          ) : null}
        </div>
      </div>
      {viewerState !== 'ready' ? (
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
          {viewerState === 'error' ? errorMessage ?? 'PLY load failed' : 'Loading PLY scene'}
        </div>
      ) : null}
    </div>
  );
}
