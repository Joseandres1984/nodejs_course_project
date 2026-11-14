import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BufferGeometry, Float32BufferAttribute, Group, Int16BufferAttribute, Mesh, SkinnedMesh, BoxGeometry, MeshStandardMaterial, Vector3 } from 'three';
import { refineFemaleLook, sculptPortraitHead } from './appearance.js';

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
  assert.equal(face.material.color.getHexString(), 'fff9f3');
  assert.equal(face.morphTargetDictionary.viseme_PP, 0);
  assert.deepEqual(face.morphTargetInfluences, [0, 0]);
  assert.equal(avatar.renderer.keyLight.intensity, 2.3);
  assert.equal(avatar.renderer.fillLight.intensity, 1.02);
  assert.equal(model.children.length, 2, 'no genera accesorios flotantes');
  assert.equal(refineFemaleLook({renderer: { model: null, face: null }}), false);
});

test('esculpe solo la mandíbula sin perder piel, UV ni visemas', () => {
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute([
    .06, 0, .65, -.06, 0, .73, .06, 0, .99,
  ], 3));
  geometry.setAttribute('uv', new Float32BufferAttribute([0, 0, .5, .5, 1, 1], 2));
  geometry.morphAttributes.position = [new Float32BufferAttribute([
    .002, 0, 0, -.002, 0, 0, 0, 0, 0,
  ], 3)];
  geometry.morphTargetsRelative = true;
  const face = new SkinnedMesh(geometry, new MeshStandardMaterial({ name: 'f020_head' }));
  const initialMorph = face.geometry.morphAttributes.position[0].getX(0);
  const initialUV = face.geometry.attributes.uv.getX(1);
  const oldGeometry = face.geometry;
  const model = new Group();
  model.add(face);
  const avatar = { renderer: { model, keyLight: { intensity: 0 }, fillLight: { intensity: 0 } } };

  assert.equal(refineFemaleLook(avatar), true);
  assert.notEqual(face.geometry, oldGeometry, 'clona geometría para no alterar el recurso compartido');
  assert.ok(face.geometry.attributes.position.getX(0) < .06, 'suaviza mandíbula');
  assert.equal(face.geometry.attributes.position.getX(2), oldGeometry.attributes.position.getX(2), 'conserva frente');
  assert.equal(face.geometry.morphAttributes.position[0].getX(0), initialMorph);
  assert.equal(face.geometry.attributes.uv.getX(1), initialUV);
  assert.equal(face.geometry.morphTargetsRelative, true);
  const sculptedX = face.geometry.attributes.position.getX(0);
  assert.equal(sculptPortraitHead(face), false, 'no deforma dos veces');
  assert.equal(face.geometry.attributes.position.getX(0), sculptedX);

  const original = new SkinnedMesh(geometry, new MeshStandardMaterial({ name: 'f020_head' }));
  const classic = new Group();
  classic.add(original);
  refineFemaleLook({ renderer: { model: classic, keyLight: {}, fillLight: {} } }, null, { sculpt: false });
  assert.equal(original.geometry, geometry, '?shape=classic no modifica proporciones');
});

test('admite posiciones cuantizadas del GLB y rechaza otros esqueletos', () => {
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Int16BufferAttribute([
    2100, 0, 22000, -2100, 0, 25300, 2100, 0, 31500,
  ], 3, true));
  const face = new SkinnedMesh(geometry, new MeshStandardMaterial({ name: 'f020_head' }));
  const x = geometry.attributes.position.getX(0);
  assert.equal(sculptPortraitHead(face), true);
  assert.ok(face.geometry.attributes.position.getX(0) < x, 'la mandíbula cuantizada conserva el ajuste');
  assert.equal(geometry.attributes.position.getX(0), x, 'el GLB original sigue intacto');

  const unrelated = new SkinnedMesh(new BoxGeometry(), new MeshStandardMaterial());
  assert.equal(sculptPortraitHead(unrelated), false, 'no altera un avatar en otro espacio local');
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

test('atlas experimental se conserva, pero el modo normal protege la boca y los ojos', () => {
  const image = readFileSync(new URL('../assets/3d/photo-face-v5.webp', import.meta.url));
  assert.ok(image.length > 100_000 && image.length < 500_000);
  assert.equal(image.toString('ascii', 0, 4), 'RIFF');
  assert.equal(image.toString('ascii', 8, 12), 'WEBP');
  const source = readFileSync(new URL('main.js', import.meta.url), 'utf8');
  assert.ok(source.includes("photo-face-v5.webp?v=41"));
  assert.ok(source.includes("search.get('identity') === 'experimental' ? PHOTO_FACE_V5 : PHOTO_FACE_CLASSIC"));
  assert.ok(source.includes("search.get('photo') !== 'off'"));
});
