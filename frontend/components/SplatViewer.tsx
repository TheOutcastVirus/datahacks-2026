'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { OrbitControls as OrbitControlsType } from 'three/examples/jsm/controls/OrbitControls.js';

type ViewerState = 'loading' | 'ready' | 'error';

export default function SplatViewer({ splatUrl }: { splatUrl: string }) {
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const isPlyAsset = splatUrl.toLowerCase().endsWith('.ply');
  const [viewerState, setViewerState] = useState<ViewerState>(
    isPlyAsset ? 'loading' : 'ready',
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const splatIframeSrc = useMemo(
    () => `/splat/viewer.html?url=${encodeURIComponent(splatUrl)}`,
    [splatUrl],
  );

  useEffect(() => {
    if (!isPlyAsset) return;

    const canvasHost = canvasHostRef.current;
    if (!canvasHost) return;

    let isDisposed = false;
    let animationFrameId = 0;
    let resizeObserver: ResizeObserver | null = null;

    let renderer: import('three').WebGLRenderer | null = null;
    let controls: OrbitControlsType | null = null;
    let geometryToDispose: import('three').BufferGeometry | null = null;
    let materialToDispose: import('three').Material | null = null;

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
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.rotateSpeed = 0.7;
        controls.zoomSpeed = 0.9;
        controls.panSpeed = 0.8;

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
            center.x + distance * 0.9,
            center.y + distance * 0.35,
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

        const animate = () => {
          if (isDisposed || !renderer) return;
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
      controls?.dispose();
      geometryToDispose?.dispose();
      materialToDispose?.dispose();
      renderer?.dispose();
      canvasHost.replaceChildren();
    };
  }, [isPlyAsset, splatUrl]);

  if (!isPlyAsset) {
    return (
      <iframe
        src={splatIframeSrc}
        className="splat-wrap"
        style={{ border: 'none', width: '100%', height: '100%', display: 'block' }}
        title="3D Gaussian Splat Viewer"
      />
    );
  }

  return (
    <div
      className="splat-wrap"
      aria-label="3D PLY viewer"
      style={{ background: '#020a12' }}
    >
      <div
        ref={canvasHostRef}
        style={{
          position: 'absolute',
          inset: 0,
        }}
      />
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
