import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { faceDepthAt, faceFeatherAt } from './cinema.js';

test('Cine mantiene detalle fotográfico y reserva profundidad para el rostro', () => {
  assert.ok(faceDepthAt(.505, .67) > faceDepthAt(.1, .1) + .05);
  assert.ok(faceDepthAt(.503, .671) > faceDepthAt(.65, .671));
  assert.ok(faceFeatherAt(.505, .698) > .99);
  assert.equal(faceFeatherAt(.01, .01), 0);
  assert.equal(faceFeatherAt(.505, .9), 0, 'no deforma cabello ni fondo');
});

test('Cine usa la fotografía original sin servicios externos y no altera el GLB estable', () => {
  const source = readFileSync(new URL('./cinema.js', import.meta.url), 'utf8');
  const bridge = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  assert.ok(source.includes('window.AURA_ASSETS'));
  assert.ok(source.includes('CAP_FPS = 30'));
  assert.ok(source.includes('devicePixelRatio || 1, 1.5'));
  assert.ok(source.includes('createCinemaAvatar'));
  assert.ok(bridge.includes("search.get('visual') === 'cine'"));
  assert.ok(bridge.includes("gender === 'femenino' && !cinemaMode"));
  assert.ok(bridge.includes('new TalkingAvatar'), 'la versión 3D estándar se conserva');
});
