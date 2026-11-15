/* AURA's own frontal geometry: measured from the ORIGINAL portrait offline.
   The camera stays conservative: single-view reconstruction cannot recover
   unseen sides, back of head, realistic hair volume or teeth. */
import { BufferGeometry, Float32BufferAttribute } from 'three';
import { PERSONAL_FACE_DATA } from './personal-face-data.mjs';

const clamp = (value, min, max) => Math.max(min, Math.min(value, max));

export function getPersonalFaceStats() {
  const { landmarks, triangles, image } = PERSONAL_FACE_DATA;
  return { vertices: landmarks.length, triangles: triangles.length / 3, image };
}

export function createPersonalFaceGeometry(width = 1.5, height = 2) {
  const { landmarks, triangles } = PERSONAL_FACE_DATA;
  if (landmarks.length !== 468 || triangles.length % 3
    || triangles.some(index => index < 0 || index >= 468)) {
    throw new Error('AURA: datos del rostro 3D inválidos');
  }
  const vertices = [];
  const uv = [];
  for (const [x, y, z] of landmarks) {
    // MediaPipe x/y describe the actual PHOTO. Preserve its exact projection
    // on first paint so the new model cannot change AURA's eyes or mouth.
    vertices.push((x - .5) * width, (.5 - y) * height,
      clamp(.036 - .64 * z, -.055, .138));
    uv.push(x, 1 - y);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3));
  geometry.setAttribute('uv', new Float32BufferAttribute(uv, 2));
  geometry.setIndex(triangles);
  geometry.computeVertexNormals();
  return geometry;
}
