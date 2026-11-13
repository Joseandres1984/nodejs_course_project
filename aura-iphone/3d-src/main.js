/* AURA 3D v1 - self-hosted 3D portraits, natural blinking and two lip-sync modes.
   MIT SDK/models: https://github.com/InterviewFlowAI/talking-avatar (pinned to 0.3.0).
   Neural audio: acoustic visemes. Native iPhone speech: approximate Spanish visemes. */
import { TalkingAvatar } from '@interviewflowai/talking-avatar';
import { createSpanishLipSync } from '../aura-3d-visemes.mjs';
import { refineFemaleLook } from './appearance.js';
import { createFacialPresence } from './presence.js';

const PREFERENCE = 'aura.3d.enabled.v1';
const ASSETS = {
  femenino: new URL('./assets/3d/female.glb', import.meta.url).href,
  masculino: new URL('./assets/3d/male.glb', import.meta.url).href,
};
const MODEL = new URL('./assets/3d/viseme-model.bin', import.meta.url).href;
const PHOTO_FACE = new URL('./assets/3d/photo-face.webp?v=36', import.meta.url).href;
// Allow a quick no-deploy comparison with the original 3D atlas (?photo=off).
const photoReferenceEnabled = new URLSearchParams(location.search).get('photo') !== 'off';
const prefersReduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
const selectedGender = () => document.querySelector('[data-gender].chosen')?.dataset.gender || 'femenino';
const storedPreference = () => {
  try { return localStorage.getItem(PREFERENCE) !== 'off'; } catch { return true; }
};
const persist = (value) => { try { localStorage.setItem(PREFERENCE, value ? 'on' : 'off'); } catch {} };

const manual = createSpanishLipSync();
const facialPresence = createFacialPresence();
let instance = null;
let visible = false;
let loading = false;
let pendingAudio = false;
let audioPlaying = false;
let phase = 'ready';
let gender = 'femenino';
let stage, mainFrame, room, layer, button, mainBadge, originalFrame, originalPosition;
let requestId = 0;

function injectStyles() {
  const style = document.createElement('style');
  style.id = 'aura3dStyles';
  style.textContent = `
    #v8Stage .aura3d-layer,#avatarFrame .aura3d-layer{position:absolute;inset:0;z-index:1;opacity:0;pointer-events:none;transition:opacity .36s ease;background:radial-gradient(ellipse at 50% 40%,#234a56,#07131d 75%)}
    #v8Stage.aura3d-live .aura3d-layer,#avatarFrame.aura3d-live .aura3d-layer{opacity:1}
    #v8Stage.aura3d-live>img,#v8Stage.aura3d-live>canvas.aura23-eye-overlay,#v8Stage.aura3d-live>img.aura-motion-ghost{visibility:hidden!important;animation:none!important}
    #avatarFrame.aura3d-live>img,#avatarFrame.aura3d-live>canvas.aura23-eye-overlay,#avatarFrame.aura3d-live>img.aura-motion-ghost{visibility:hidden!important;animation:none!important}
    #v8Stage .aura3d-toggle{z-index:4;max-width:70%;cursor:pointer;top:14px;right:13px;font:inherit;letter-spacing:.02em;touch-action:manipulation}
    #v8Stage .aura3d-toggle:focus-visible{outline:2px solid #f7fbff;outline-offset:3px}
    #v8Stage .aura3d-layer>canvas,#avatarFrame .aura3d-layer>canvas{width:100%;height:100%;display:block}
    #avatarFrame #faceMode.aura3d-main-toggle{cursor:pointer;border-radius:7px;padding:7px;border:1px solid #7cfde780;background:rgba(8,37,43,.72);font-size:9px;letter-spacing:.02em;text-align:center;max-width:56%}
    #avatarFrame #faceMode.aura3d-main-toggle:focus-visible{outline:2px solid white;outline-offset:3px}
    #v8Stage.aura3d-live:after{z-index:2;background:linear-gradient(transparent 73%,rgba(4,15,26,.85))}
    #v8Stage .v8-person{z-index:3}
    @media(prefers-reduced-motion:reduce){#v8Stage .aura3d-layer,#avatarFrame .aura3d-layer{transition:none}}
  `;
  document.head.appendChild(style);
}

function updateButton(label) {
  const status = label || (visible ? '3D activo · Ver foto' : 'Foto 2D · Activar 3D');
  if (button) {
    button.textContent = status;
    button.setAttribute('aria-pressed', String(visible));
  }
  if (mainBadge) {
    mainBadge.textContent = label || (visible ? '● ROSTRO 3D · VER FOTO' : 'FOTO 2D · ACTIVAR 3D');
    mainBadge.setAttribute('aria-pressed', String(visible));
  }
}

function syncSurface() {
  if (!layer || !stage || !mainFrame) return;
  const target = room?.classList.contains('is-open') ? stage : mainFrame;
  if (layer.parentElement !== target) target.insertBefore(layer, target.firstChild);
  stage.classList.toggle('aura3d-live', visible && target === stage);
  mainFrame.classList.toggle('aura3d-live', visible && target === mainFrame);
}

function show3D(value) {
  const wasVisible = visible;
  visible = !!value && !!instance && !loading;
  syncSurface();
  // The 2D portrait is always preserved for low-end devices or errors.
  updateButton();
  if (visible && !wasVisible) animatePresence();
}

function applyPhase(value) {
  phase = value;
  if (instance) instance.setStatus(phase === 'thinking' ? 'thinking' : 'listening');
}

async function ensureInstance() {
  if (instance || loading) return;
  loading = true;
  updateButton('Preparando rostro 3D…');
  const gen = ++requestId;
  let avatar;
  try {
    gender = selectedGender();
    avatar = new TalkingAvatar({
      container: layer,
      avatarUrl: ASSETS[gender],
      modelUrl: MODEL,
      onError(error) { console.warn('AURA 3D:', error.message || error); },
    });
    await avatar.ready;
    if (gen !== requestId) { avatar.dispose(); return; }
    instance = avatar;
    instance.setStatus(phase === 'thinking' ? 'thinking' : 'listening');
    if (gender === 'femenino') refineFemaleLook(avatar, photoReferenceEnabled ? PHOTO_FACE : null);
    // The pinned MIT SDK intentionally keeps its render callback internal.
    // v0.3.0's instance method is extendable; native Safari TTS needs this
    // bridge because speechSynthesis never exposes its audio waveform.
    if (typeof avatar.frameNow === 'function') {
      originalFrame = avatar.frameNow.bind(avatar);
      avatar.frameNow = () => manual.active
        ? { visemes: manual.frame(), mode: 'speaking' }
        : originalFrame();
    }
    originalPosition = {
      x: avatar.renderer?.model?.position.x || 0,
      y: avatar.renderer?.model?.position.y || 0,
      rotationX: avatar.renderer?.model?.rotation.x || 0,
      rotationY: avatar.renderer?.model?.rotation.y || 0,
    };
    loading = false;
    show3D(storedPreference());
  } catch (error) {
    loading = false;
    if (avatar) avatar.dispose();
    console.warn('AURA 3D: no se pudo iniciar WebGL o cargar el modelo', error);
    show3D(false);
    updateButton('3D no disponible · Reintentar');
  }
}

function animatePresence() {
  if (!instance || !stage || !visible) return;
  // Gentle full 3D head movement, with stable eye-level framing.
  const model = instance.renderer?.model;
  if (model && originalPosition) {
    const now = performance.now();
    const t = now / 1000;
    const reduced = prefersReduced() || !visible || document.hidden;
    const mul = reduced ? 0 : 1;
    const speaking = manual.active || audioPlaying || phase === 'speaking';
    const gaze = facialPresence.update(instance.renderer, { timeMs: now, speaking, reduced });
    model.rotation.y = originalPosition.rotationY + mul * (Math.sin(t * .57) * .048 + (speaking ? .018 : 0)) + gaze.yaw;
    model.rotation.x = originalPosition.rotationX + mul * (Math.sin(t * .37) * .019 + (speaking ? Math.sin(t * 2.2) * .012 : 0)) + gaze.pitch;
    model.position.y = originalPosition.y + mul * Math.sin(t * 1.16) * .004;
    model.position.x = originalPosition.x + mul * Math.sin(t * .45) * .004;
  }
  requestAnimationFrame(animatePresence);
}

function syncGender() {
  const next = selectedGender();
  if (!instance || gender === next) return;
  gender = next;
  facialPresence.reset();
  instance.setAvatar(ASSETS[next])
    .then(() => { if (next === 'femenino' && instance) refineFemaleLook(instance, photoReferenceEnabled ? PHOTO_FACE : null); })
    .catch(() => updateButton('No cargó el rostro · Foto 2D'));
}

function mount() {
  stage = document.getElementById('v8Stage');
  mainFrame = document.getElementById('avatarFrame');
  room = document.getElementById('v8Room');
  if (!stage || !mainFrame || document.getElementById('aura3dToggle')) return;
  injectStyles();
  const oldBadge = stage.querySelector('.v8-chip');
  button = document.createElement('button');
  button.id = 'aura3dToggle';
  button.type = 'button';
  button.className = 'v8-chip aura3d-toggle';
  button.setAttribute('aria-label', 'Alternar avatar 3D y fotografía 2D');
  oldBadge?.replaceWith(button);
  if (!oldBadge) stage.appendChild(button);
  layer = document.createElement('div');
  layer.className = 'aura3d-layer';
  layer.setAttribute('aria-hidden', 'true');
  syncSurface();

  async function toggleMode() {
    if (loading) return;
    if (visible) {
      persist(false);
      endSpeech();
      show3D(false);
      instance?.dispose();
      instance = null;
      facialPresence.reset();
    } else {
      persist(true);
      if (instance) show3D(true);
      else await ensureInstance();
    }
  }
  button.addEventListener('click', toggleMode);
  mainBadge = document.getElementById('faceMode');
  if (mainBadge) {
    mainBadge.classList.add('aura3d-main-toggle');
    mainBadge.setAttribute('role', 'button');
    mainBadge.setAttribute('tabindex', '0');
    mainBadge.setAttribute('aria-label', 'Alternar rostro 3D y fotografía 2D');
    mainBadge.addEventListener('click', toggleMode);
    mainBadge.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleMode(); }
    });
  }
  if (room) new MutationObserver(syncSurface).observe(room, { attributes: true, attributeFilter: ['class'] });
  new MutationObserver(() => applyPhase(stage.dataset.phase || 'ready'))
    .observe(stage, { attributes: true, attributeFilter: ['data-phase'] });
  const genderChooser = document.querySelector('.avatar-options');
  if (genderChooser) new MutationObserver(syncGender).observe(genderChooser, {
    attributes: true, subtree: true, attributeFilter: ['class'],
  });
  applyPhase(stage.dataset.phase || 'ready');
  updateButton('Iniciando 3D…');
  if (storedPreference()) ensureInstance();
  else updateButton();
}

function beginSpeech(text) {
  if (!visible || !instance || pendingAudio) return;
  manual.start(text);
}

function endSpeech() {
  manual.stop();
  pendingAudio = false;
  if (audioPlaying) instance?.stopSpeaking();
  audioPlaying = false;
}

function prepareAudio() {
  if (!visible || !instance) return false;
  pendingAudio = true;
  manual.stop();
  return true;
}

async function speakAudio(blob) {
  if (!visible || !instance || !blob) throw Error('3D no disponible');
  pendingAudio = false;
  audioPlaying = true;
  try { await instance.speak(blob); }
  finally { audioPlaying = false; }
}

window.Aura3D = {
  beginSpeech,
  endSpeech,
  word(event) { if (visible) manual.boundary(event); },
  level(value) { if (visible) manual.level(value); },
  canSpeakAudio() { return visible && !!instance; },
  prepareAudio,
  speakAudio,
  audioFailed() { pendingAudio = false; },
  setStatus: applyPhase,
  state() { return { visible, loaded: !!instance, loading, gender, phase, manual: manual.active, audioPlaying }; },
};

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
else mount();
