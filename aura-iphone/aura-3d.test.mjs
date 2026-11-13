import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { createSpanishLipSync, buildSpanishVisemes } from './aura-3d-visemes.mjs';

test('el habla española contiene labios cerrados y cinco formas de vocales', () => {
  const forms = buildSpanishVisemes('Mamá, papá, feliz voz.');
  assert.ok(forms.some(v => v.viseme === 'PP'));
  assert.ok(forms.some(v => v.viseme === 'FF'));
  assert.ok(forms.some(v => v.viseme === 'aa'));
  assert.ok(forms.some(v => v.viseme === 'E'));
  assert.ok(forms.some(v => v.viseme === 'I'));
  assert.ok(forms.some(v => v.viseme === 'O'));
  assert.ok(forms.some(v => v.viseme === 'U') === false);
  assert.ok(forms.some(v => !v.viseme));
});

test('el modelo labial sigue el tiempo, se resincroza por palabra y se detiene', () => {
  let currentTime = 0;
  const lip = createSpanishLipSync(() => currentTime);
  lip.start('AURA es tu asistente');
  assert.equal(lip.active, true);
  currentTime = 48;
  assert.ok((lip.frame().aa || 0) > 0.1);
  currentTime = 1200;
  lip.boundary({ text: 'Habla mamá', charIndex: 6 });
  currentTime = 1240;
  assert.ok((lip.frame().PP || 0) > 0.1, 'la m cierra los labios');
  lip.stop();
  assert.equal(lip.active, false);
  assert.deepEqual(lip.frame(), {});
});

test('la integración mantiene ambos avatares locales y salida 2D segura', () => {
  const base = new URL('.', import.meta.url);
  const server = readFileSync(new URL('server.mjs', base), 'utf8');
  const html = readFileSync(new URL('index.html', base), 'utf8');
  const source = readFileSync(new URL('3d-src/main.js', base), 'utf8');
  assert.ok(server.includes('aura-3d.bundle.js?v=34'));
  assert.ok(server.includes('".glb":"model/gltf-binary"'));
  assert.ok(html.includes('window.Aura3D?.beginSpeech?.(lastReply)'));
  assert.ok(html.includes('await window.Aura3D.speakAudio(blob)'));
  assert.ok(source.includes('instance.speak(blob)'));
  assert.ok(source.includes("mainFrame.classList.toggle('aura3d-live'"));
  assert.ok(source.includes("stage.classList.toggle('aura3d-live'"));
  assert.ok(source.includes('new MutationObserver(syncSurface)'));
  assert.ok(!source.includes('canUse3D()'), 'el WebGL se intenta sin falso negativo previo');
  for (const f of ['female.glb', 'male.glb']) {
    const content = readFileSync(new URL('assets/3d/' + f, base));
    assert.equal(content.toString('ascii', 0, 4), 'glTF');
    assert.ok(content.length > 250_000);
    const jsonLength = content.readUInt32LE(12);
    const model = JSON.parse(content.subarray(20, 20 + jsonLength).toString());
    const morphs = model.meshes.flatMap(m => m.extras?.targetNames || []);
    assert.ok(morphs.includes('viseme_PP'), 'puede cerrar la boca para P, B y M');
    assert.ok(morphs.includes('viseme_aa'), 'puede abrir la boca para A');
    assert.ok(morphs.includes('eyeBlinkLeft'), 'puede parpadear');
    assert.ok(morphs.length >= 50, 'incluye un rig facial 3D completo');
  }
  assert.ok(statSync(new URL('assets/3d/viseme-model.bin', base)).size > 500_000);
  assert.ok(statSync(new URL('aura-3d.bundle.js', base)).size > 100_000);
});
