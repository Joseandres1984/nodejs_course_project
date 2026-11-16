import { test } from 'node:test';
import assert from 'node:assert/strict';
import { softenRiggedVisemes } from './rigged-lips.js';

test('modera la apertura grande sin perder el cierre de labios', () => {
  const original = { aa: 1, O: .8, PP: .98, FF: .7, nn: .55 };
  const result = softenRiggedVisemes(original);
  assert.equal(result.aa, .82);
  assert.equal(result.O, .8 * .82);
  assert.equal(result.PP, .98 * .93);
  assert.ok(result.PP > result.aa, 'conserva los cierres para consonantes');
  assert.equal(original.aa, 1, 'no modifica el fotograma original del SDK');
});

test('mantiene el silencio y evita intensidades fuera del rango', () => {
  const rest = {};
  assert.equal(softenRiggedVisemes(rest), rest);
  assert.deepEqual(softenRiggedVisemes({ aa: 4, U: -1, PP: Number.NaN }), { aa: .82, U: 0, PP: 0 });
});
