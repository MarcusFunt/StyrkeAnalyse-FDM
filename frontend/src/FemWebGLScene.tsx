import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { FemFieldPreview } from "./lib/femRun";
import {
  buildFieldMeshData,
  colorForFieldValue,
  type FemFieldKey,
  type FemFieldMeshData,
} from "./lib/femViewer";

export interface FemSurfaceInspection {
  sourceCell: number;
  value: number;
}

interface FemWebGLSceneProps {
  preview: FemFieldPreview;
  field: FemFieldKey;
  yaw: number;
  resetRevision: number;
  showEdges: boolean;
  onReady: () => void;
  onUnavailable: () => void;
  onInspection: (inspection: FemSurfaceInspection | null) => void;
}

function createVertexColors(data: FemFieldMeshData, field: FemFieldKey): Float32Array {
  const colors = new Float32Array(data.positions.length);
  data.triangleValues.forEach((value, triangleIndex) => {
    const color = new THREE.Color(colorForFieldValue(value, field, data.range));
    for (let vertex = 0; vertex < 3; vertex += 1) {
      color.toArray(colors, triangleIndex * 9 + vertex * 3);
    }
  });
  return colors;
}

function disposeMaterial(material: THREE.Material | THREE.Material[]) {
  if (Array.isArray(material)) material.forEach((item) => item.dispose());
  else (material as THREE.Material).dispose();
}

function createGroundGrid(geometry: THREE.BufferGeometry): THREE.LineSegments {
  geometry.computeBoundingBox();
  const bounds = geometry.boundingBox ?? new THREE.Box3(new THREE.Vector3(-2, -2, -0.2), new THREE.Vector3(2, 2, 0.2));
  const boxSize = new THREE.Vector3();
  bounds.getSize(boxSize);
  const size = Math.max(4, boxSize.x, boxSize.y) * 1.55;
  const half = size / 2;
  const spacing = size / 12;
  const floorZ = bounds.min.z - Math.max(0.12, boxSize.z * 0.42);
  const positions: number[] = [];
  const colors: number[] = [];
  for (let index = 0; index <= 12; index += 1) {
    const offset = -half + index * spacing;
    const color = index % 3 === 0 ? new THREE.Color("#54717d") : new THREE.Color("#304d59");
    positions.push(offset, -half, floorZ, offset, half, floorZ, -half, offset, floorZ, half, offset, floorZ);
    for (let line = 0; line < 4; line += 1) color.toArray(colors, colors.length);
  }
  const gridGeometry = new THREE.BufferGeometry();
  gridGeometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  gridGeometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  const grid = new THREE.LineSegments(gridGeometry, new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.5,
    depthWrite: false,
  }));
  grid.renderOrder = -1;
  return grid;
}

export default function FemWebGLScene(props: FemWebGLSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const meshRef = useRef<THREE.Mesh | null>(null);
  const edgeRef = useRef<THREE.LineSegments | null>(null);
  const fieldDataRef = useRef<FemFieldMeshData | null>(null);
  const fieldRef = useRef(props.field);
  const yawRef = useRef(props.yaw);
  const showEdgesRef = useRef(props.showEdges);
  const callbacksRef = useRef(props);
  fieldRef.current = props.field;
  yawRef.current = props.yaw;
  showEdgesRef.current = props.showEdges;
  callbacksRef.current = props;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
    } catch {
      callbacksRef.current.onUnavailable();
      return;
    }

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.01, 1000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = false;
    controls.enablePan = false;
    controls.screenSpacePanning = false;
    controls.target.set(0, 0, 0);
    const data = buildFieldMeshData(props.preview, fieldRef.current);
    const surfaceGeometry = new THREE.BufferGeometry();
    surfaceGeometry.setAttribute("position", new THREE.BufferAttribute(data.positions, 3));
    surfaceGeometry.setAttribute("color", new THREE.BufferAttribute(createVertexColors(data, fieldRef.current), 3));
    surfaceGeometry.computeVertexNormals();
    surfaceGeometry.computeBoundingSphere();
    const surface = new THREE.Mesh(surfaceGeometry, new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.72,
      metalness: 0.02,
      side: THREE.DoubleSide,
    }));
    const edgeGeometry = new THREE.EdgesGeometry(surfaceGeometry, 18);
    const edgeLines = new THREE.LineSegments(edgeGeometry, new THREE.LineBasicMaterial({
      color: "#b8cbd4",
      transparent: true,
      opacity: 0.47,
      depthWrite: false,
    }));
    edgeLines.visible = showEdgesRef.current;
    const floorGrid = createGroundGrid(surfaceGeometry);

    const hemisphere = new THREE.HemisphereLight("#e1f2fa", "#263b43", 1.5);
    hemisphere.position.set(0, 0, 1);
    scene.add(surface, edgeLines, floorGrid, hemisphere);
    const keyLight = new THREE.DirectionalLight("#fff3df", 2.1);
    keyLight.position.set(4, -4, 8);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight("#76b6c7", 0.8);
    fillLight.position.set(-5, 3, 2);
    scene.add(fillLight);

    const radius = Math.max(surfaceGeometry.boundingSphere?.radius ?? 2, 0.5);
    const cameraDistance = radius * 3.4;
    const baseDirection = new THREE.Vector3(0.75, -1.35, 0.95).normalize();
    const zAxis = new THREE.Vector3(0, 0, 1);
    const resetCamera = (yaw: number) => {
      const direction = baseDirection.clone().applyAxisAngle(zAxis, ((yaw + 35) * Math.PI) / 180);
      camera.position.copy(direction.multiplyScalar(cameraDistance));
      camera.lookAt(0, 0, 0);
      controls.target.set(0, 0, 0);
      controls.minDistance = radius * 1.05;
      controls.maxDistance = radius * 12;
      controls.update();
    };
    resetCamera(yawRef.current);
    controls.saveState();

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(rect.width, rect.height, false);
      camera.aspect = rect.width / rect.height;
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);
    };
    const render = () => renderer.render(scene, camera);
    controls.addEventListener("change", render);
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    window.addEventListener("resize", resize);
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const inspect = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const face = raycaster.intersectObject(surface, false)[0]?.faceIndex;
      const currentData = fieldDataRef.current;
      if (face === undefined || face === null || !currentData || face >= currentData.triangleValues.length) {
        callbacksRef.current.onInspection(null);
        return;
      }
      callbacksRef.current.onInspection({
        sourceCell: currentData.sourceCells[face],
        value: currentData.triangleValues[face],
      });
    };
    const clearInspection = () => callbacksRef.current.onInspection(null);
    const contextLost = (event: Event) => {
      event.preventDefault();
      callbacksRef.current.onUnavailable();
    };
    canvas.addEventListener("pointermove", inspect);
    canvas.addEventListener("pointerleave", clearInspection);
    canvas.addEventListener("webglcontextlost", contextLost);
    rendererRef.current = renderer;
    sceneRef.current = scene;
    cameraRef.current = camera;
    controlsRef.current = controls;
    meshRef.current = surface;
    edgeRef.current = edgeLines;
    fieldDataRef.current = data;
    resize();
    callbacksRef.current.onReady();

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resize);
      controls.removeEventListener("change", render);
      canvas.removeEventListener("pointermove", inspect);
      canvas.removeEventListener("pointerleave", clearInspection);
      canvas.removeEventListener("webglcontextlost", contextLost);
      controls.dispose();
      surface.geometry.dispose();
      disposeMaterial(surface.material);
      edgeLines.geometry.dispose();
      disposeMaterial(edgeLines.material);
      floorGrid.geometry.dispose();
      disposeMaterial(floorGrid.material);
      renderer.dispose();
      renderer.forceContextLoss();
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
      meshRef.current = null;
      edgeRef.current = null;
      fieldDataRef.current = null;
    };
  }, [props.preview]);

  useEffect(() => {
    const surface = meshRef.current;
    if (!surface) return;
    const data = buildFieldMeshData(props.preview, props.field);
    const colorAttribute = new THREE.BufferAttribute(createVertexColors(data, props.field), 3);
    surface.geometry.setAttribute("color", colorAttribute);
    fieldDataRef.current = data;
    callbacksRef.current.onInspection(null);
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    if (scene && camera) rendererRef.current?.render(scene, camera);
  }, [props.preview, props.field]);

  useEffect(() => {
    if (edgeRef.current) edgeRef.current.visible = props.showEdges;
    const renderer = rendererRef.current;
    const camera = cameraRef.current;
    const scene = sceneRef.current;
    if (renderer && camera && scene) renderer.render(scene, camera);
  }, [props.showEdges]);

  useEffect(() => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const renderer = rendererRef.current;
    const scene = sceneRef.current;
    if (!camera || !controls || !renderer || !scene) return;
    const radius = Math.max(meshRef.current?.geometry.boundingSphere?.radius ?? 2, 0.5);
    const distance = radius * 3.4;
    const direction = new THREE.Vector3(0.75, -1.35, 0.95).normalize()
      .applyAxisAngle(new THREE.Vector3(0, 0, 1), ((props.yaw + 35) * Math.PI) / 180);
    camera.position.copy(direction.multiplyScalar(distance));
    camera.lookAt(0, 0, 0);
    controls.target.set(0, 0, 0);
    controls.update();
    renderer.render(scene, camera);
  }, [props.yaw, props.resetRevision]);

  return (
    <canvas
      ref={canvasRef}
      className="fem-webgl-canvas"
      role="img"
      aria-label={`Interactive 3D ${props.field.replaceAll("_", " ")} field over ${props.preview.triangles.length.toLocaleString()} boundary triangles. Drag to orbit and scroll to zoom.`}
    />
  );
}
