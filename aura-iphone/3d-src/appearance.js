/* AURA personal look. Keep the model's 67 original facial morph targets intact.
   Approximate the photo's styling while a photo-derived 3D head is developed.
   No camera, biometric scan, paid API, or additional network assets required. */
import {
  CatmullRomCurve3, CylinderGeometry, Group, Mesh, MeshStandardMaterial, TorusGeometry,
  TubeGeometry, Vector3,
} from 'three';

const TONES = {
  clothing: '#292c32',
  skin: '#ffefe6',
  hair: '#b2a29b',
  strands: '#2d211e',
  earrings: '#d9e0dd',
};

export function refineFemaleLook(avatar) {
  const scene = avatar?.renderer?.model;
  const face = avatar?.renderer?.face;
  if (!scene || !face) return false;

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

  const features = new Group();
  features.name = 'AuraReferenceStyling';
  const at = (x, y, z) => new Vector3(face.x + x, face.y + y, face.z + z);

  // A simple high black knit collar masks the model's V-neck jacket. Unlike
  // a flat overlay, it has depth and follows the avatar's 3D head turns.
  const knit = new MeshStandardMaterial({ color: '#0b0d12', roughness: 1, side: 2 });
  const collar = new Mesh(new CylinderGeometry(.054, .067, .12, 28, 1, true), knit);
  collar.position.copy(at(0, -.235, -.075));
  collar.name = 'BlackTurtleneck';
  features.add(collar);

  // The reference has small silver hoop earrings.
  const silver = new MeshStandardMaterial({ color: TONES.earrings, metalness: .8, roughness: .29 });
  for (const side of [-1, 1]) {
    const ring = new Mesh(new TorusGeometry(.011, .0022, 7, 20), silver);
    ring.position.copy(at(side * .083, -.073, -.033));
    features.add(ring);
  }

  // Soft loose brunette hairs around the temples, like the portrait.
  // All geometry is attached to the rotating character, not to the viewport.
  const brown = new MeshStandardMaterial({ color: TONES.strands, roughness: 1 });
  for (const [side, length, sway] of [[-1, -.24, -.02], [-1, -.16, .013], [1, -.25, .025], [1, -.145, -.013]]) {
    const strand = new CatmullRomCurve3([
      at(side * .067, .129, -.009),
      at(side * (.087 + sway), .050, .037),
      at(side * (.091 + sway), -.048, .046),
      at(side * (.084 + sway), length, .036),
    ]);
    features.add(new Mesh(new TubeGeometry(strand, 18, .0012, 4, false), brown));
  }
  scene.add(features);

  // Preserve an intimate photographic portrait instead of harsh studio light.
  const renderer = avatar.renderer;
  renderer.keyLight.intensity = 3.1;
  renderer.fillLight.intensity = 1.25;
  return true;
}
