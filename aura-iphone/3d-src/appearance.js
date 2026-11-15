/* AURA personal look. Keep the model's 67 original facial morph targets intact.
   Uses a baked frontal image projection, keeping the skinned geometry and
   articulated eyes, teeth and lips intact. No paid services at runtime. */
import { SRGBColorSpace, TextureLoader } from 'three';

const TONES = {
  clothing: '#17191d',
  skin: '#fff9f3',
  hair: '#b2a29b',
};

// The 1024px reference atlas already has photographed shadows and highlights.
// A gentler studio profile reduces baked-light + PBR double illumination.
const STUDIO = Object.freeze({
  skin: '#f5eeeb',
  keyIntensity: 1.48,
  fillIntensity: 0.82,
  environmentIntensity: 0.26,
  exposure: 0.89,
});

const smoothstep = (a, b, value) => {
  const t = Math.max(0, Math.min(1, (value - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

// Rocketbox's head uses a local Z-up space, roughly Z=.59 (chin) to 1
// (forehead). Small proportion adjustments are safe in that local frame;
// deforming the rig, UVs or the relative facial morph targets is not.
export function sculptPortraitHead(mesh, { profile = 'classic' } = {}) {
  if (!mesh?.isSkinnedMesh || mesh.userData.auraPortraitSculpt) return false;
  const position = mesh.geometry?.attributes?.position;
  if (!position || position.itemSize !== 3 || position.count < 3) return false;

  let minZ = Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < position.count; i++) {
    const z = position.getZ(i);
    minZ = Math.min(minZ, z);
    maxZ = Math.max(maxZ, z);
  }
  // Do not sculpt unexpected/custom avatars with another coordinate frame.
  if (minZ < .5 || maxZ > 1.08 || maxZ < .66) return false;

  const geometry = mesh.geometry.clone();
  const vertices = geometry.attributes.position;
  const study = profile === 'study';
  for (let i = 0; i < vertices.count; i++) {
    const x = vertices.getX(i);
    const y = vertices.getY(i);
    const z = vertices.getZ(i);
    const jaw = 1 - smoothstep(.66, .855, z);
    const cheek = smoothstep(.745, .815, z) * (1 - smoothstep(.86, .925, z));
    // The opt-in portrait study gently narrows the lower jaw and nose bridge,
    // emphasizing the cheeks of AURA's original photograph. It does not
    // stretch the eye sockets or alter viseme / eyelid morph target buffers.
    const nose = study
      ? (1 - smoothstep(.019, .042, Math.abs(x)))
        * smoothstep(.69, .745, z) * (1 - smoothstep(.79, .845, z)) : 0;
    const width = 1 - (study ? .108 : .052) * jaw
      + (study ? .023 : .009) * cheek - .027 * nose;
    vertices.setXYZ(i, x * width, y, z);
  }
  vertices.needsUpdate = true;
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  // geometry.clone() also preserves skinIndices, skinWeights, UVs and all
  // 67 morph target position buffers, including visemes and eyelid motion.
  mesh.geometry = geometry;
  mesh.userData.auraPortraitSculpt = study ? 'portrait-study-v42' : 'v39';
  return true;
}

export function refineFemaleLook(avatar, photoTextureUrl, { sculpt = true, profile = 'classic', graphics = 'classic' } = {}) {
  const scene = avatar?.renderer?.model;
  if (!scene) return false;
  const studio = graphics === 'studio';

  scene.traverse(child => {
    if (!child.isMesh) return;
    const head = (Array.isArray(child.material) ? child.material : [child.material])
      .some(material => material?.name?.endsWith('_head'));
    if (sculpt && head) sculptPortraitHead(child, { profile });
    const customize = material => {
      if (!material?.isMeshStandardMaterial) return material;
      const name = material.name || '';
      if (!/(body|head|opacity)$/.test(name)) return material;
      const copy = material.clone();
      // The source model wears a grey pinstripe suit. Darken its fabric so
      // the silhouette recalls the reference's black turtleneck instead.
      if (name.endsWith('_body')) copy.color.set(TONES.clothing);
      else if (name.endsWith('_head')) copy.color.set(studio ? STUDIO.skin : TONES.skin);
      else copy.color.set(TONES.hair);
      copy.roughness = name.endsWith('_head') ? (studio ? .96 : .93) : .94;
      return copy;
    };
    child.material = Array.isArray(child.material)
      ? child.material.map(customize) : customize(child.material);
  });

  // The color atlas is pre-baked from the selected AURA portrait. Texture
  // replacement does not modify the GLB's mesh, armature or 67 blendshapes.
  // A failed image request simply leaves the original 3D face in place.
  if (photoTextureUrl && typeof document !== 'undefined') {
    new TextureLoader().loadAsync(photoTextureUrl).then(texture => {
      if (!scene.parent || avatar.renderer?.model !== scene) {
        texture.dispose();
        return;
      }
      texture.flipY = false; // glTF UV orientation differs from DOM images.
      texture.colorSpace = SRGBColorSpace;
      texture.anisotropy = Math.min(8, avatar.renderer?.renderer?.capabilities?.getMaxAnisotropy?.() || 4);
      texture.needsUpdate = true;
      scene.traverse(child => {
        if (!child.isMesh) return;
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        for (const mat of mats) {
          if (!mat?.name?.endsWith('_head')) continue;
          mat.map = texture;
          mat.needsUpdate = true;
        }
      });
    }).catch(error => console.warn('AURA: textura fotográfica no disponible; conservando cara original', error));
  }

  // The reference photograph already contains studio highlights. Softer
  // PBR illumination prevents re-lighting them into bright painted patches.
  const renderer = avatar.renderer;
  renderer.keyLight.intensity = studio ? STUDIO.keyIntensity : 2.3;
  renderer.fillLight.intensity = studio ? STUDIO.fillIntensity : 1.02;
  if (studio) {
    if (renderer.scene) renderer.scene.environmentIntensity = STUDIO.environmentIntensity;
    if (renderer.renderer) renderer.renderer.toneMappingExposure = STUDIO.exposure;
  }
  return true;
}
