/* AURA personal look. Keep the model's 67 original facial morph targets intact.
   Uses a baked frontal image projection, keeping the skinned geometry and
   articulated eyes, teeth and lips intact. No paid services at runtime. */
import { SRGBColorSpace, TextureLoader } from 'three';

const TONES = {
  clothing: '#17191d',
  skin: '#fff6ef',
  hair: '#b2a29b',
};

export function refineFemaleLook(avatar, photoTextureUrl) {
  const scene = avatar?.renderer?.model;
  if (!scene) return false;

  scene.traverse(child => {
    if (!child.isMesh) return;
    const customize = material => {
      if (!material?.isMeshStandardMaterial) return material;
      const name = material.name || '';
      if (!/(body|head|opacity)$/.test(name)) return material;
      const copy = material.clone();
      // The source model wears a grey pinstripe suit. Darken its fabric so
      // the silhouette recalls the reference's black turtleneck instead.
      if (name.endsWith('_body')) copy.color.set(TONES.clothing);
      else if (name.endsWith('_head')) copy.color.set(TONES.skin);
      else copy.color.set(TONES.hair);
      copy.roughness = name.endsWith('_head') ? .82 : .94;
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
      texture.anisotropy = 4;
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

  // Preserve an intimate photographic portrait instead of harsh studio light.
  const renderer = avatar.renderer;
  renderer.keyLight.intensity = 3.1;
  renderer.fillLight.intensity = 1.25;
  return true;
}
