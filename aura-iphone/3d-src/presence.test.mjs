import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createFacialPresence } from './presence.js';

test('mirada coordinada y movimientos faciales muy sutiles', () => {
  const controller = createFacialPresence(() => .99);
  const shapes = {};
  const renderer = { setMorph(name, target) { shapes[name] = target; } };
  for (let timeMs = 0; timeMs <= 1000; timeMs += 20) {
    controller.update(renderer, { timeMs, speaking: false });
  }
  assert.equal(shapes.eyeLookInLeft, shapes.eyeLookOutRight);
  assert.equal(shapes.eyeLookOutLeft, shapes.eyeLookInRight);
  assert.ok(shapes.eyeLookInLeft > 0 && shapes.eyeLookInLeft <= .05);
  assert.ok(shapes.eyeSquintLeft > 0 && shapes.eyeSquintLeft < .10);
  assert.ok(shapes.mouthSmileRight > 0 && shapes.mouthSmileRight < .10);
  for (const forbidden of ['jawOpen', 'eyeBlinkLeft', 'browInnerUp', 'viseme_aa']) {
    assert.equal(shapes[forbidden], undefined);
  }
});

test('al hablar suaviza la sonrisa y hace gestos breves sin ciclos mecánicos', () => {
  const controller = createFacialPresence(() => .1);
  const shapes = {};
  const renderer = { setMorph(name, target) { shapes[name] = target; } };
  for (let t = 0; t <= 1200; t += 20) controller.update(renderer, { timeMs: t });
  const restingSmile = shapes.mouthSmileLeft;
  let maximumNod = 0;
  for (let t = 1220; t <= 2400; t += 20) {
    const pose = controller.update(renderer, { timeMs: t, speaking: true });
    maximumNod = Math.max(maximumNod, pose.nod);
  }
  assert.ok(shapes.mouthSmileLeft < restingSmile, 'no deja una sonrisa fija al hablar');
  assert.ok(maximumNod > 0 && maximumNod < .013, 'asiente una sola vez, suavemente');
  assert.equal(controller.update(renderer, { timeMs: 2420 }).nod, 0);
  controller.update(renderer, { timeMs: 2500, reduced: true });
  assert.equal(shapes.mouthSmileLeft, 0);
  assert.equal(shapes.eyeSquintRight, 0);
  controller.reset();
  assert.deepEqual(controller.update(null, { timeMs: 300 }), { yaw: 0, pitch: 0, nod: 0 });
});

test('mirada de atención más estable y ausencia de gestos en movimiento reducido', () => {
  const controller = createFacialPresence(() => .92);
  const shapes = {};
  const renderer = { setMorph(name, value) { shapes[name] = value; } };
  let pose;
  for (let t = 0; t <= 1200; t += 20) {
    pose = controller.update(renderer, { timeMs: t, phase: 'thinking' });
  }
  assert.ok(Math.abs(pose.yaw) < .009, 'gira la cabeza menos de medio grado');
  assert.ok(Math.abs(pose.pitch) < .004);
  pose = controller.update(renderer, { timeMs: 1220, reduced: true, speaking: true });
  assert.equal(pose.nod, 0);
  assert.equal(shapes.eyeLookDownLeft, 0);
  assert.equal(shapes.mouthSmileRight, 0);
});

test('modo estudio entorna los párpados sin afectar el parpadeo original', () => {
  const reference = {}, stable = {};
  const studyController = createFacialPresence(() => .5);
  const stableController = createFacialPresence(() => .5);
  const studyRenderer = { setMorph(name, value) { reference[name] = value; } };
  const stableRenderer = { setMorph(name, value) { stable[name] = value; } };
  for (let t = 0; t <= 900; t += 20) {
    studyController.update(studyRenderer, { timeMs: t, portraitStudy: true });
    stableController.update(stableRenderer, { timeMs: t });
  }
  assert.ok(reference.eyeSquintLeft > stable.eyeSquintLeft + .06);
  assert.ok(reference.eyeSquintRight > stable.eyeSquintRight + .05);
  assert.ok(reference.mouthSmileLeft > stable.mouthSmileLeft);
  assert.equal(reference.eyeBlinkLeft, undefined, 'el SDK conserva los parpadeos');
  studyController.update(studyRenderer, { timeMs: 920, portraitStudy: true, reduced: true });
  assert.equal(reference.eyeSquintLeft, 0, 'respeta movimiento reducido');
});

test('studio mantiene ojos menos abiertos y sonrisa pequeña sin interferir visemas', () => {
  const shapes = {};
  const renderer = { setMorph(name, value) { shapes[name] = value; } };
  const controller = createFacialPresence(() => .5);
  for (let t = 0; t < 1500; t += 20) {
    controller.update(renderer, { timeMs: t, portraitStudy: true, studioGraphics: true });
  }
  assert.ok(shapes.eyeSquintLeft >= .19 && shapes.eyeSquintLeft < .22);
  assert.ok(shapes.eyeSquintRight < shapes.eyeSquintLeft);
  assert.ok(shapes.mouthSmileLeft > 0 && shapes.mouthSmileLeft < .06);
  for (const protectedMorph of ['eyeBlinkLeft', 'eyeBlinkRight', 'jawOpen', 'viseme_aa']) {
    assert.equal(shapes[protectedMorph], undefined);
  }
});
