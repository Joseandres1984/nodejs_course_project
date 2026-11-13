/* AURA personal look. Keep the model's 67 original facial morph targets intact.
   The reference photo needs a new head mesh for a faithful likeness.
   Until then, use discreet material styling only: experimental hair strands,
   earrings and neckline primitives proved disconnected on the real iPhone. */

const TONES = {
  clothing: '#17191d',
  skin: '#fff6ef',
  hair: '#b2a29b',
};

export function refineFemaleLook(avatar) {
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

  // Preserve an intimate photographic portrait instead of harsh studio light.
  const renderer = avatar.renderer;
  renderer.keyLight.intensity = 3.1;
  renderer.fillLight.intensity = 1.25;
  return true;
}
