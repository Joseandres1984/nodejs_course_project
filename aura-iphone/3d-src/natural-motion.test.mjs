import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createNaturalMotion } from './natural-motion.js';

function seededRandom() {
  let seed = 123456;
  return () => ((seed = (1664525 * seed + 1013904223) >>> 0) / 2 ** 32);
}

test('mantiene contacto visual al comenzar y varía suavemente sin vaivén periódico', () => {
  const motion = createNaturalMotion(seededRandom());
  const samples = [];
  for (let t = 0; t <= 44000; t += 20) {
    const pose = motion.update({ timeMs: t, phase: 'listening' });
    samples.push(pose);
    assert.ok(Math.abs(pose.yaw) <= .021);
    assert.ok(Math.abs(pose.pitch) <= .023);
    assert.ok(Math.abs(pose.roll) <= .003);
    assert.ok(Math.abs(pose.lift) <= .0007);
    assert.ok(Math.abs(pose.shift) <= .0006);
  }
  assert.deepEqual(samples[0], { yaw: 0, pitch: 0, roll: 0, lift: 0, shift: 0 });
  assert.deepEqual(samples[40], samples[0], 'no se balancea mientras establece contacto visual');
  assert.ok(samples.some(p => Math.abs(p.yaw) > .004), 'realiza algún cambio de atención');
  assert.ok(samples.every((p, i) => i === 0 || Math.abs(p.yaw - samples[i - 1].yaw) < .0006),
    'cada fotograma se mueve poco');
  // A sine loop would return to the same angle and repeat identically.
  assert.ok(Math.abs(samples[250].yaw - samples[900].yaw) > .0001);
});

test('adapta el gesto al habla y no genera un nuevo ciclo de cabeceo', () => {
  const motion = createNaturalMotion(seededRandom());
  for (let t = 0; t <= 1000; t += 20) motion.update({ timeMs: t });
  const before = motion.update({ timeMs: 1020 });
  for (let t = 1040; t <= 3000; t += 20) motion.update({ timeMs: t, speaking: true });
  const during = motion.update({ timeMs: 3020, speaking: true, speechNod: .008 });
  const withoutNod = motion.update({ timeMs: 3020, speaking: true });
  assert.ok(during.pitch - withoutNod.pitch > .0079, 'el nod del habla responde a la voz');
  assert.notDeepEqual(before, withoutNod, 'ajusta la postura al empezar a hablar');
});

test('pausa en segundo plano y respetar movimiento reducido devuelve postura neutral', () => {
  const motion = createNaturalMotion(seededRandom());
  for (let t = 0; t <= 9000; t += 20) motion.update({ timeMs: t });
  const neutral = { yaw: 0, pitch: 0, roll: 0, lift: 0, shift: 0 };
  assert.deepEqual(motion.update({ timeMs: 9020, reduced: true }), neutral);
  assert.deepEqual(motion.update({ timeMs: 9040, hidden: true }), neutral);
  assert.deepEqual(motion.update({ timeMs: 200000 }), neutral, 'no salta tras reanudar Safari');
  for (let t = 200020; t <= 204000; t += 20) motion.update({ timeMs: t });
  assert.deepEqual(motion.update({ timeMs: 204020, reduced: true }), neutral);
  motion.reset();
  assert.deepEqual(motion.update({ timeMs: 1 }), neutral);
});
