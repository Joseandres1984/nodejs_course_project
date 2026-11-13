import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Group, Mesh, BoxGeometry, MeshStandardMaterial, Vector3 } from 'three';
import { refineFemaleLook } from './appearance.js';

test('adapta el estilo al retrato sin borrar los morphs faciales', () => {
  const model = new Group();
  const shirt = new Mesh(new BoxGeometry(), new MeshStandardMaterial({ name: 'f020_body' }));
  const face = new Mesh(new BoxGeometry(), new MeshStandardMaterial({ name: 'f020_head' }));
  face.morphTargetDictionary = { viseme_PP: 0, viseme_aa: 1 };
  face.morphTargetInfluences = [0, 0];
  model.add(shirt, face);
  const avatar = { renderer: { model, face: new Vector3(0, 1.5, 0), keyLight: { intensity: 4 }, fillLight: { intensity: 1 } } };
  assert.equal(refineFemaleLook(avatar), true);
  assert.equal(shirt.material.color.getHexString(), '17191d');
  assert.equal(face.material.color.getHexString(), 'fff6ef');
  assert.equal(face.morphTargetDictionary.viseme_PP, 0);
  assert.deepEqual(face.morphTargetInfluences, [0, 0]);
  assert.equal(model.children.length, 2, 'no genera accesorios flotantes');
  assert.equal(refineFemaleLook({renderer: { model: null, face: null }}), false);
});

test('usa textura del retrato en WebP sin tocar los blendshapes', () => {
  const image = readFileSync(new URL('../assets/3d/photo-face.webp', import.meta.url));
  assert.ok(image.length > 25_000);
  assert.equal(image.toString('ascii', 0, 4), 'RIFF');
  assert.equal(image.toString('ascii', 8, 12), 'WEBP');
  const source = readFileSync(new URL('appearance.js', import.meta.url), 'utf8');
  assert.ok(source.includes('texture.flipY = false'));
  assert.ok(source.includes("if (!mat?.name?.endsWith('_head')) continue"));
});
