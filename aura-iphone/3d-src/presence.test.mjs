import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createFacialPresence } from './presence.js';

test('mirada coordinada y movimientos faciales muy sutiles', () => {
  const controller = createFacialPresence(() => .99);
  const shapes = {};
  const renderer = { setMorph(name, target) { shapes[name] = target; } };
  controller.update(renderer, { timeMs: 0 });
  controller.update(renderer, { timeMs: 1000, speaking: false });
  assert.equal(shapes.eyeLookInLeft, shapes.eyeLookOutRight);
  assert.equal(shapes.eyeLookOutLeft, shapes.eyeLookInRight);
  assert.ok(shapes.eyeLookInLeft > 0 && shapes.eyeLookInLeft <= .08);
  assert.ok(shapes.eyeSquintLeft > 0 && shapes.eyeSquintLeft < .10);
  assert.ok(shapes.mouthSmileRight > 0 && shapes.mouthSmileRight < .10);
  for (const forbidden of ['jawOpen', 'eyeBlinkLeft', 'browInnerUp', 'viseme_aa']) {
    assert.equal(shapes[forbidden], undefined);
  }
});

test('mientras habla evita sonrisa fija y respeta movimiento reducido', () => {
  const controller = createFacialPresence(() => .1);
  const shapes = {};
  const renderer = { setMorph(name, target) { shapes[name] = target; } };
  controller.update(renderer, { timeMs: 10 });
  controller.update(renderer, { timeMs: 50, speaking: true });
  assert.equal(shapes.mouthSmileLeft, .040);
  controller.update(renderer, { timeMs: 150, reduced: true });
  assert.equal(shapes.mouthSmileLeft, 0);
  assert.equal(shapes.eyeSquintRight, 0);
  controller.reset();
  assert.deepEqual(controller.update(null, { timeMs: 300 }), { yaw: 0, pitch: 0 });
});
