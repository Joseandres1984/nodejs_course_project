import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { faceBlendMask, photoAffine } from './rigged-photo.js';

test('El rostro original se registra sobre ojos y boca de una cabeza 3D', () => {
  const source = [{ x: .30, y: .35 }, { x: .70, y: .35 }, { x: .50, y: .57 }];
  const target = [{ x: .45, y: .27 }, { x: .60, y: .26 }, { x: .53, y: .37 }];
  const project = photoAffine(source, target);
  for (let i = 0; i < source.length; i++) {
    const p = project(source[i]);
    assert.ok(Math.abs(p.x - target[i].x) < .000001);
    assert.ok(Math.abs(p.y - target[i].y) < .000001);
  }
  assert.throws(() => photoAffine([source[0],source[0],source[0]],target), /degenerada/);
});

test('La foto suaviza los bordes faciales y no tiñe la nuca ni el fondo', () => {
  assert.ok(faceBlendMask(.53, .313, 1) > .9);
  assert.equal(faceBlendMask(.02, .02, 1), 0);
  assert.equal(faceBlendMask(.53, .313, -.5), 0);
  assert.ok(faceBlendMask(.71, .39, 1) < faceBlendMask(.53, .313, 1));
});

test('El modo 3D humano utiliza modelo completo y articulado; la foto frontal permanece como alternativa', () => {
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const shader = readFileSync(new URL('./rigged-photo.js', import.meta.url), 'utf8');
  assert.ok(source.includes("search.get('visual') === 'rigged'"));
  assert.ok(source.includes('projectPhotoOntoRig(avatar'));
  assert.ok(source.includes('new TalkingAvatar'), 'cabeza y cuerpo 3D completos');
  assert.ok(source.includes('createCinemaAvatar'), 'mantiene la referencia fotográfica');
  assert.ok(shader.includes('mesh.geometry.clone()'), 'nunca modifica el GLB compartido');
  assert.ok(shader.includes('auraPhotoWeight'));
  assert.ok(shader.includes('model.getObjectByName'));
  assert.ok(shader.includes('getVertexPosition'));
  assert.ok(shader.includes('includeFaceDetails'), 'corrige las piezas pequeñas de nariz y labios');
  assert.ok(shader.includes('Math.ceil(position.count * .12)'), 'cobertura proporcional a cada submalla');
});

test('el modelo real tiene detalles faciales pequeños que ya no deben quedar sin textura', () => {
  const binary = readFileSync(new URL('../assets/3d/female.glb', import.meta.url));
  const jsonLength = binary.readUInt32LE(12);
  const gltf = JSON.parse(binary.subarray(20, 20 + jsonLength).toString('utf8'));
  const headSizes = gltf.meshes.flatMap(mesh => mesh.primitives)
    .filter(primitive => gltf.materials[primitive.material]?.name?.endsWith('_head'))
    .map(primitive => gltf.accessors[primitive.attributes.POSITION].count);
  assert.ok(headSizes.some(count => count < 100), 'la nariz o los labios son submallas separadas');
  const source = readFileSync(new URL('./rigged-photo.js', import.meta.url), 'utf8');
  assert.ok(!source.includes('|| mesh.geometry.attributes.position.count < 500'),
    'los detalles pequeños no pueden eliminarse incondicionalmente');
});
