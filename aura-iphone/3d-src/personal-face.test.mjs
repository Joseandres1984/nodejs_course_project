import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createPersonalFaceGeometry, getPersonalFaceStats } from './personal-face.js';

test('Rostro personal mide 468 puntos originales y 852 triángulos reales', () => {
  const { vertices, triangles, image } = getPersonalFaceStats();
  assert.equal(vertices, 468);
  assert.equal(triangles, 852);
  assert.deepEqual(image, [720, 960]);
});

test('Rostro personal conserva la proyección fotográfica y añade relieve real', () => {
  const mesh = createPersonalFaceGeometry();
  const vertices = mesh.getAttribute('position');
  const uv = mesh.getAttribute('uv');
  assert.equal(vertices.count, 468);
  assert.equal(mesh.index.count, 2556);
  let minDepth = Infinity, maxDepth = -Infinity;
  for (let i = 0; i < vertices.count; i++) {
    assert.ok(Math.abs(vertices.getX(i) - (uv.getX(i) - .5) * 1.5) < .000001);
    assert.ok(Math.abs(vertices.getY(i) - (uv.getY(i) - .5) * 2) < .000001);
    minDepth = Math.min(minDepth, vertices.getZ(i));
    maxDepth = Math.max(maxDepth, vertices.getZ(i));
  }
  assert.ok(maxDepth - minDepth > .075, 'relieve de nariz, mejillas y mandíbula');
  mesh.dispose();
});

test('Malla nueva solo se activa con visual=personal; mantiene fallback 2D y avatar estable', () => {
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const shader = readFileSync(new URL('./cinema.js', import.meta.url), 'utf8');
  assert.ok(source.includes("search.get('visual') === 'personal'"));
  assert.ok(source.includes('if (personalMode) return true'), 'el enlace personal fuerza el arranque aunque Safari recuerde foto 2D');
  assert.ok(source.includes('Falló 3D ('), 'un error de WebGL no debe confundirse con una foto activada');
  assert.ok(source.includes('new TalkingAvatar'));
  assert.ok(source.includes('show3D(false)'));
  assert.ok(shader.includes('createPersonalFaceGeometry'));
  assert.ok(shader.includes('? createPersonalFaceGeometry'));
  assert.ok(shader.includes('CAP_FPS = 30'));
});
