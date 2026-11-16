/* AURA rigged study: a REAL skeletal, morph-enabled 3D person, with the
   original portrait gently projected onto her face. Unlike the earlier
   photo-depth mesh, the hair, skull, eyelids, jaw and shoulders are genuine
   articulated 3D geometry. The Rocketbox/Three.js base stays MIT licensed.

   Important: photo projection matches three visible facial landmarks only.
   We make no claim of recovering the unseen sides of the source photograph.
*/
import { Float32BufferAttribute, SRGBColorSpace, TextureLoader, Vector3 } from 'three';
import { PERSONAL_FACE_DATA } from './personal-face-data.mjs';

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
export function smoothstep(low, high, x) {
  const t = clamp((x - low) / (high - low), 0, 1);
  return t * t * (3 - 2 * t);
}

// Two eyes and the top lip constrain an affine mapping of the actual rig
// screen-space coordinates to the photographic coordinates.
export function photoAffine(source, target) {
  if (source.length !== 3 || target.length !== 3) throw new Error('AURA: faltan rasgos de alineación');
  const [p, q, r] = source, [a, b, c] = target;
  const px = q.x - p.x, py = q.y - p.y;
  const qx = r.x - p.x, qy = r.y - p.y;
  const determinant = px * qy - py * qx;
  if (!Number.isFinite(determinant) || Math.abs(determinant) < .00001) {
    throw new Error('AURA: alineación de ojos y boca degenerada');
  }
  const coeffs = key => {
    const e = b[key] - a[key], f = c[key] - a[key];
    const slopeX = (e * qy - f * py) / determinant;
    const slopeY = (f * px - e * qx) / determinant;
    return [slopeX, slopeY, a[key] - slopeX * p.x - slopeY * p.y];
  };
  const u = coeffs('x'), v = coeffs('y');
  return point => ({ x: u[0] * point.x + u[1] * point.y + u[2],
    y: v[0] * point.x + v[1] * point.y + v[2] });
}

export function faceBlendMask(u, v, front = 1) {
  const radius = Math.hypot((u - .53) / .205, (v - .313) / .173);
  return .94 * (1 - smoothstep(.78, 1.07, radius)) * smoothstep(-.12, .36, front);
}

const facePoint = (a, b) => {
  const p = PERSONAL_FACE_DATA.landmarks[a], q = PERSONAL_FACE_DATA.landmarks[b];
  return { x: (p[0] + q[0]) / 2, y: (p[1] + q[1]) / 2 };
};
const photoEyes = [facePoint(33, 133), facePoint(263, 362)].sort((a, b) => a.x - b.x);
const mouth = { x: PERSONAL_FACE_DATA.landmarks[13][0], y: PERSONAL_FACE_DATA.landmarks[13][1] };
const imageAssetKey = './assets/motion/femenino-0.webp';

function screenPoint(world, camera) {
  const ndc = world.project(camera);
  return { x: (1 + ndc.x) / 2, y: (1 - ndc.y) / 2 };
}

export async function projectPhotoOntoRig(avatar, imageAssets = window.AURA_ASSETS, { includeFaceDetails = true } = {}) {
  const renderer = avatar?.renderer;
  const model = renderer?.model, camera = renderer?.camera;
  if (!model || !camera || !String(imageAssets?.[imageAssetKey] || '').startsWith('data:image/')) {
    throw new Error('AURA: faltan modelo, cámara o fotografía original');
  }
  model.updateMatrixWorld(true);
  camera.updateMatrixWorld(true);

  const world = name => {
    const bone = model.getObjectByName(name);
    if (!bone) throw new Error(`AURA: falta articulación ${name}`);
    return screenPoint(bone.getWorldPosition(new Vector3()), camera);
  };
  const eyeWorld = [world('Bip01_REye'), world('Bip01_LEye')].sort((a, b) => a.x - b.x);
  const transform = photoAffine([...eyeWorld, world('Bip01_MUpperLip')], [...photoEyes, mouth]);
  const texture = await new TextureLoader().loadAsync(imageAssets[imageAssetKey]);
  texture.colorSpace = SRGBColorSpace;
  texture.anisotropy = Math.min(4, renderer?.renderer?.capabilities?.getMaxAnisotropy?.() || 4);
  if (!model.parent || avatar.renderer?.model !== model) { texture.dispose(); return false; }

  let applied = 0;
  model.traverse(mesh => {
    if (!mesh?.isSkinnedMesh || !mesh.geometry?.attributes?.normal) return;
    const baseMaterial = mesh.material;
    if (Array.isArray(baseMaterial) || !baseMaterial?.name?.endsWith('_head')
      || !baseMaterial.isMeshStandardMaterial) return;

    // Small _head primitives are separate facial details (including nose and
    // mouth geometry). Ignoring them left the underlying low-res material
    // visible as sharp, contrasting triangular patches over the photograph.
    if (!includeFaceDetails && mesh.geometry.attributes.position.count < 500) return;

    const geometry = mesh.geometry.clone();
    const position = geometry.attributes.position;
    const normal = geometry.attributes.normal;
    const photoUv = new Float32Array(position.count * 2);
    const weights = new Float32Array(position.count);
    const point = new Vector3(), vertex = new Vector3(), n = new Vector3(), toCamera = new Vector3();
    let influence = 0;
    for (let i = 0; i < position.count; i++) {
      mesh.getVertexPosition(i, point);
      vertex.copy(point);
      mesh.localToWorld(vertex);
      const imagePoint = transform(screenPoint(vertex.clone(), camera));
      photoUv[i * 2] = clamp(imagePoint.x, .003, .997);
      photoUv[i * 2 + 1] = 1 - clamp(imagePoint.y, .003, .997);
      n.set(normal.getX(i), normal.getY(i), normal.getZ(i)).transformDirection(mesh.matrixWorld);
      toCamera.copy(camera.position).sub(vertex).normalize();
      const weight = faceBlendMask(imagePoint.x, imagePoint.y, n.dot(toCamera));
      weights[i] = weight;
      if (weight > .4) influence++;
    }
    // A 59-vertex lip or 72-vertex nose can never meet the former 30-vertex
    // visibility threshold reliably. Scale it to the mesh's own size.
    const minimumCoverage = Math.min(30, Math.max(5, Math.ceil(position.count * .12)));
    if (influence < minimumCoverage) { geometry.dispose(); return; }

    geometry.setAttribute('auraPhotoUv', new Float32BufferAttribute(photoUv, 2));
    geometry.setAttribute('auraPhotoWeight', new Float32BufferAttribute(weights, 1));
    const material = baseMaterial.clone();
    material.color.set('#ffffff');
    material.roughness = .96;
    material.metalness = 0;
    material.onBeforeCompile = shader => {
      shader.uniforms.auraSourcePortrait = { value: texture };
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `#include <common>
          attribute vec2 auraPhotoUv;
          attribute float auraPhotoWeight;
          varying vec2 vAuraPhotoUv;
          varying float vAuraPhotoWeight;`)
        .replace('#include <begin_vertex>', `#include <begin_vertex>
          vAuraPhotoUv = auraPhotoUv;
          vAuraPhotoWeight = auraPhotoWeight;`);
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>
          uniform sampler2D auraSourcePortrait;
          varying vec2 vAuraPhotoUv;
          varying float vAuraPhotoWeight;`)
        .replace('#include <map_fragment>', `#ifdef USE_MAP
          vec4 baseTexel = texture2D(map, vMapUv);
          vec4 photoTexel = texture2D(auraSourcePortrait, vAuraPhotoUv);
          diffuseColor *= mix(baseTexel, photoTexel, clamp(vAuraPhotoWeight, 0.0, 0.94));
          #endif`);
    };
    material.customProgramCacheKey = () => 'aura-rigged-personal-photo-v49';
    geometry.computeBoundingSphere();
    mesh.geometry = geometry;
    mesh.material = material;
    mesh.userData.auraPersonalRig = true;
    applied++;
  });
  if (!applied) { texture.dispose(); return false; }
  // Texture lifetime matches this avatar. Release it with the renderer when
  // the app switches avatars; the stable GLB and underlying maps are intact.
  model.userData.auraRigPhotoTexture = texture;
  return true;
}
