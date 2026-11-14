
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import GlobeControls from "./GlobeControls";
import "../../fire-map/styles/globe.css";

const INITIAL_CAMERA_POSITION = [0, 0, 3.5];

export default function EarthGlobe({ onLocationSelect, markers = [] }) {
  const containerRef = useRef(null);
  const controlsRef = useRef(null);
  const cameraRef = useRef(null);
  const earthRef = useRef(null);
  const onLocationSelectRef = useRef(onLocationSelect);
  const selectedMarkerRef = useRef(null);

  // Rotation is derived: it spins only while there is nothing to look at,
  // unless the user explicitly toggles it (null = automatic).
  const [rotationOverride, setRotationOverride] = useState(null);
  const isAutoRotating = rotationOverride ?? markers.length === 0;
  const rotationRef = useRef(isAutoRotating);
  const fittedRef = useRef(false);

  useEffect(() => {
    rotationRef.current = isAutoRotating;
    if (controlsRef.current) controlsRef.current.autoRotate = isAutoRotating;
  }, [isAutoRotating]);

  // Keep the latest callback without recreating the Three.js scene.
  useEffect(() => {
    onLocationSelectRef.current = onLocationSelect;
  }, [onLocationSelect]);

  useEffect(() => {
    const container = containerRef.current;

    if (!container) return;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#050b16");

    // Camera
    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / container.clientHeight,
      0.1,
      1000
    );

    camera.position.set(...INITIAL_CAMERA_POSITION);
    cameraRef.current = camera;

    // Renderer
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
    });

    renderer.setPixelRatio(
      Math.min(window.devicePixelRatio, 2)
    );

    renderer.setSize(
      container.clientWidth,
      container.clientHeight
    );

    renderer.outputColorSpace = THREE.SRGBColorSpace;

    container.appendChild(renderer.domElement);

    // Lighting
    const ambientLight = new THREE.AmbientLight(
      0xffffff,
      1.5
    );

    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(
      0xffffff,
      2
    );

    directionalLight.position.set(5, 3, 5);
    scene.add(directionalLight);

    // Earth Mesh
    const earthGeometry = new THREE.SphereGeometry(
      1,
      64,
      64
    );

    // Earth Texture. The image ships with the app (public/textures) so the
    // globe renders the same on any network; if it still fails the material
    // falls back to a solid ocean-blue instead of staying black.
    const textureLoader = new THREE.TextureLoader();

    const earthMaterial = new THREE.MeshPhongMaterial({
      color: 0x1e3a8a,
      shininess: 10,
    });

    const earthTexture = textureLoader.load(
      `${import.meta.env.BASE_URL}textures/earth_atmos_2048.jpg`,
      (texture) => {
        texture.colorSpace = THREE.SRGBColorSpace;
        earthMaterial.map = texture;
        earthMaterial.color.set(0xffffff);
        earthMaterial.needsUpdate = true;
      },
      undefined,
      () => {
        earthMaterial.map = null;
        earthMaterial.needsUpdate = true;
      }
    );

    const earth = new THREE.Mesh(
      earthGeometry,
      earthMaterial
    );

    scene.add(earth);
    earthRef.current = earth;

    // Selected Location Marker
    const clearSelectedMarker = () => {
      const marker = selectedMarkerRef.current;

      if (!marker) return;

      earth.remove(marker);

      marker.traverse((child) => {
        if (child.geometry) {
          child.geometry.dispose();
        }

        if (child.material) {
          if (Array.isArray(child.material)) {
            child.material.forEach((material) =>
              material.dispose()
            );
          } else {
            child.material.dispose();
          }
        }
      });

      selectedMarkerRef.current = null;
    };

    // Atmosphere
    const atmosphereGeometry = new THREE.SphereGeometry(
      1.035,
      64,
      64
    );

    const atmosphereMaterial = new THREE.MeshBasicMaterial({
      color: 0x3b82f6,
      transparent: true,
      opacity: 0.12,
      side: THREE.BackSide,
    });

    const atmosphere = new THREE.Mesh(
      atmosphereGeometry,
      atmosphereMaterial
    );

    scene.add(atmosphere);

    // Starfield
    const starGeometry = new THREE.BufferGeometry();
    const starPositions = [];

    for (let i = 0; i < 1500; i++) {
      const radius = 35 + Math.random() * 30;

      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(
        2 * Math.random() - 1
      );

      const x =
        radius * Math.sin(phi) * Math.cos(theta);

      const y =
        radius * Math.sin(phi) * Math.sin(theta);

      const z = radius * Math.cos(phi);

      starPositions.push(x, y, z);
    }

    starGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(starPositions, 3)
    );

    const starMaterial = new THREE.PointsMaterial({
      color: 0xffffff,
      size: 0.09,
      transparent: true,
      opacity: 0.8,
      sizeAttenuation: true,
    });

    const stars = new THREE.Points(
      starGeometry,
      starMaterial
    );

    scene.add(stars);

    // Orbit Controls
    const controls = new OrbitControls(
      camera,
      renderer.domElement
    );

    controls.enableDamping = true;
    controls.dampingFactor = 0.05;

    controls.enablePan = false;

    controls.minDistance = 1.6;
    controls.maxDistance = 6;

    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.5;

    controlsRef.current = controls;

    // Geographic Point Selection
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    let pointerDownPosition = null;

    const handlePointerDown = (event) => {
      pointerDownPosition = {
        x: event.clientX,
        y: event.clientY,
      };
    };

    const handleClick = (event) => {
      if (!pointerDownPosition) return;

      const distance = Math.hypot(
        event.clientX - pointerDownPosition.x,
        event.clientY - pointerDownPosition.y
      );

      pointerDownPosition = null;

      // Ignore globe dragging
      if (distance > 5) return;

      const rect = renderer.domElement.getBoundingClientRect();

      pointer.x =
        ((event.clientX - rect.left) / rect.width) * 2 - 1;

      pointer.y =
        -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(pointer, camera);

      const intersections = raycaster.intersectObject(earth);

      if (intersections.length === 0) return;

      const localPoint = earth.worldToLocal(
        intersections[0].point.clone()
      );

      // Remove previous marker
      clearSelectedMarker();

      // Create marker group
      const markerGroup = new THREE.Group();

      // Get normalized position on Earth
      const markerPosition = localPoint.clone().normalize();

      // Position marker slightly above Earth's surface
      markerGroup.position
        .copy(markerPosition)
        .multiplyScalar(1.012);

      // Marker sphere
      const markerGeometry = new THREE.SphereGeometry(
        0.018,
        16,
        16
      );

      const markerMaterial = new THREE.MeshBasicMaterial({
        color: 0xff6b00,
      });

      const markerSphere = new THREE.Mesh(
        markerGeometry,
        markerMaterial
      );

      markerGroup.add(markerSphere);

      // Outer ring
      const ringGeometry = new THREE.TorusGeometry(
        0.035,
        0.003,
        8,
        48
      );

      const ringMaterial = new THREE.MeshBasicMaterial({
        color: 0xffa500,
      });

      const ring = new THREE.Mesh(
        ringGeometry,
        ringMaterial
      );

      // Align ring with Earth's surface
      ring.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 0, 1),
        markerPosition
      );

      markerGroup.add(ring);

      // Add marker to Earth
      earth.add(markerGroup);

      selectedMarkerRef.current = markerGroup;

      const latitude =
        Math.asin(
          localPoint.y / localPoint.length()
        ) *
        (180 / Math.PI);

      let longitude =
        Math.atan2(
          localPoint.z,
          -localPoint.x
        ) *
          (180 / Math.PI) -
        180;

      // Normalize longitude to -180 ... 180
      longitude =
        ((longitude + 180) % 360 + 360) % 360 - 180;

      onLocationSelectRef.current?.({
        latitude: Number(latitude.toFixed(4)),
        longitude: Number(longitude.toFixed(4)),
      });
    };

    renderer.domElement.addEventListener(
      "pointerdown",
      handlePointerDown
    );

    renderer.domElement.addEventListener(
      "click",
      handleClick
    );

    // Animation Loop
    let animationFrameId;

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);

      controls.update();
      renderer.render(scene, camera);
    };

    animate();

    // Handle Resize
    const resizeObserver = new ResizeObserver(() => {
      const width = container.clientWidth;
      const height = container.clientHeight;

      if (!width || !height) return;

      camera.aspect = width / height;
      camera.updateProjectionMatrix();

      renderer.setSize(width, height);
    });

    resizeObserver.observe(container);

    // Cleanup
    return () => {
      cancelAnimationFrame(animationFrameId);

      resizeObserver.disconnect();

      renderer.domElement.removeEventListener(
        "pointerdown",
        handlePointerDown
      );

      renderer.domElement.removeEventListener(
        "click",
        handleClick
      );

      controls.dispose();
      clearSelectedMarker();

      earthGeometry.dispose();
      earthMaterial.dispose();
      earthTexture.dispose();

      atmosphereGeometry.dispose();
      atmosphereMaterial.dispose();

      starGeometry.dispose();
      starMaterial.dispose();

      renderer.dispose();

      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }

      controlsRef.current = null;
      cameraRef.current = null;
    };
  }, []);

  // Fire layers: one Points object per kind so colours stay independent.
  useEffect(() => {
    const earth = earthRef.current;

    if (!earth) return;

    const layers = [];
    const groups = { modis: [], viirs: [], anomaly: [], harmonized: [] };

    markers.forEach((marker) => {
      if (!marker || !Number.isFinite(marker.lat) || !Number.isFinite(marker.lon)) return;
      const bucket = groups[marker.kind];
      if (bucket) bucket.push(marker);
    });

    const addPoints = (list, color, size, radius) => {
      if (!list.length) return;

      const positions = new Float32Array(list.length * 3);

      list.forEach((marker, index) => {
        const phi = THREE.MathUtils.degToRad(marker.lat);
        const lambda = THREE.MathUtils.degToRad(marker.lon);

        positions[index * 3] = radius * Math.cos(phi) * Math.cos(lambda);
        positions[index * 3 + 1] = radius * Math.sin(phi);
        positions[index * 3 + 2] = -radius * Math.cos(phi) * Math.sin(lambda);
      });

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

      const material = new THREE.PointsMaterial({
        color,
        size,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
      });

      const points = new THREE.Points(geometry, material);
      points.frustumCulled = false;
      earth.add(points);
      layers.push({ points, geometry, material });
    };

    addPoints(groups.modis, 0xff7a1a, 0.009, 1.004);
    addPoints(groups.viirs, 0xffd23f, 0.009, 1.004);
    addPoints(groups.anomaly, 0xff2d2d, 0.014, 1.012);
    // Harmonized cell-days sit just above the globe so they stay visible
    // next to the detections that fall inside the same cell.
    addPoints(groups.harmonized, 0xa855f7, 0.02, 1.02);

    // Aim the camera at the data instead of the prime meridian, otherwise a
    // small regional cluster (e.g. one country) is a few invisible pixels.
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (camera && controls && markers.length && !fittedRef.current) {
      fittedRef.current = true;
      const center = new THREE.Vector3();
      markers.forEach((marker) => {
        const phi = THREE.MathUtils.degToRad(marker.lat);
        const lambda = THREE.MathUtils.degToRad(marker.lon);
        center.x += Math.cos(phi) * Math.cos(lambda);
        center.y += Math.sin(phi);
        center.z += -Math.cos(phi) * Math.sin(lambda);
      });
      if (center.length() > 0.0001) {
        const direction = center.normalize();
        const distance = 2.45;
        camera.position.copy(direction.clone().multiplyScalar(distance));
        controls.target.set(0, 0, 0);
        controls.autoRotate = rotationRef.current;
        controls.update();
      }
    }

    return () => {
      layers.forEach(({ points, geometry, material }) => {
        earth.remove(points);
        geometry.dispose();
        material.dispose();
      });
    };
  }, [markers]);

  // Zoom In
  const handleZoomIn = () => {
    const camera = cameraRef.current;

    if (!camera) return;

    camera.position.multiplyScalar(0.85);
    controlsRef.current?.update();
  };

  // Zoom Out
  const handleZoomOut = () => {
    const camera = cameraRef.current;

    if (!camera) return;

    camera.position.multiplyScalar(1.15);
    controlsRef.current?.update();
  };

  // Reset Camera and Clear Selection
  const handleReset = () => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;

    if (!camera || !controls) return;

    // Remove selected point
    const marker = selectedMarkerRef.current;

    if (marker) {
      marker.parent?.remove(marker);

      marker.traverse((child) => {
        if (child.geometry) {
          child.geometry.dispose();
        }

        if (child.material) {
          if (Array.isArray(child.material)) {
            child.material.forEach((material) =>
              material.dispose()
            );
          } else {
            child.material.dispose();
          }
        }
      });

      selectedMarkerRef.current = null;
    }

    // Clear selected location in parent component
    onLocationSelectRef.current?.(null);

    // Reset camera: back to the data cluster, or to the default view when the
    // store has no points yet.
    const points = markers.filter(
      (marker) => Number.isFinite(marker?.lat) && Number.isFinite(marker?.lon)
    );

    if (points.length) {
      const center = new THREE.Vector3();
      points.forEach((marker) => {
        const phi = THREE.MathUtils.degToRad(marker.lat);
        const lambda = THREE.MathUtils.degToRad(marker.lon);
        center.x += Math.cos(phi) * Math.cos(lambda);
        center.y += Math.sin(phi);
        center.z += -Math.cos(phi) * Math.sin(lambda);
      });
      if (center.length() > 0.0001) {
        camera.position.copy(center.normalize().multiplyScalar(2.45));
      } else {
        camera.position.set(...INITIAL_CAMERA_POSITION);
      }
    } else {
      camera.position.set(...INITIAL_CAMERA_POSITION);
    }

    controls.target.set(0, 0, 0);
    controls.autoRotate = false;
    controls.update();

    setRotationOverride(null);
  };

  // Toggle Auto Rotation
  const handleToggleRotation = () => {
    const controls = controlsRef.current;

    if (!controls) return;

    controls.autoRotate = !isAutoRotating;
    setRotationOverride(!isAutoRotating);
  };

  return (
    <div
      ref={containerRef}
      className="earth-globe-container"
    >
      <GlobeControls
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onReset={handleReset}
        onToggleRotation={handleToggleRotation}
        isAutoRotating={isAutoRotating}
      />
    </div>
  );
}
