/* AURA 3D v1 - self-hosted 3D portraits, natural blinking and two lip-sync modes.
   MIT SDK/models: https://github.com/InterviewFlowAI/talking-avatar (pinned to 0.3.0).
   Neural audio: acoustic visemes. Native iPhone speech: approximate Spanish visemes. */
import { TalkingAvatar } from '@interviewflowai/talking-avatar';
import { createSpanishLipSync } from '../aura-3d-visemes.mjs';

const PREFERENCE = 'aura.3d.enabled.v1';
const ASSETS = {
  femenino: new URL('./assets/3d/female.glb', import.meta.url).href,
  masculino: new URL('./assets/3d/male.glb', import.meta.url).href,
};
const MODEL = new URL('./assets/3d/viseme-model.bin', import.meta.url).href;
const prefersReduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
const selectedGender = () => document.querySelector('[data-gender].chosen')?.dataset.gender || 'femenino';
const storedPreference = () => {
  try { return localStorage.getItem(PREFERENCE) !== 'off'; } catch { return true; }
};
const persist = (value) => { try { localStorage.setItem(PREFERENCE, value ? 'on' : 'off'); } catch {} };

const manual = createSpanishLipSync();
let instance = null;
let visible = false;
let loading = false;
let pendingAudio = false;
let audioPlaying = false;
let phase = 'ready';
let gender = 'femenino';
let stage, layer, button, oldBadge, originalFrame, originalPosition;
let requestId = 0;

function canUse3D() {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', { powerPreference: 'low-power' });
    if (!gl) return false;
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return true;
  } catch { return false; }
}

function injectStyles() {
  const style = document.createElement('style');
  style.id = 'aura3dStyles';
  style.textContent = `
    #v8Stage .aura3d-layer{position:absolute;inset:0;z-index:1;opacity:0;pointer-events:none;transition:opacity .36s ease;background:radial-gradient(ellipse at 50% 40%,#234a56,#07131d 75%)}
    #v8Stage.aura3d-live .aura3d-layer{opacity:1}
    #v8Stage.aura3d-live>img,#v8Stage.aura3d-live>canvas.aura23-eye-overlay,#v8Stage.aura3d-live>img.aura-motion-ghost{visibility:hidden!important;animation:none!important}
    #v8Stage .aura3d-toggle{z-index:4;max-width:70%;cursor:pointer;top:14px;right:13px;font:inherit;letter-spacing:.02em;touch-action:manipulation}
    #v8Stage .aura3d-toggle:focus-visible{outline:2px solid #f7fbff;outline-offset:3px}
    #v8Stage .aura3d-layer>canvas{width:100%;height:100%;display:block}
    #v8Stage.aura3d-live:after{z-index:2;background:linear-gradient(transparent 73%,rgba(4,15,26,.85))}
    #v8Stage .v8-person{z-index:3}
    @media(prefers-reduced-motion:reduce){#v8Stage .aura3d-layer{transition:none}}
  `;
  document.head.appendChild(style);
}

function updateButton(label) {
  if (!button) return;
  button.textContent = label || (visible ? '3D activo · Ver foto' : 'Foto 2D · Activar 3D');
  button.setAttribute('aria-pressed', String(visible));
}

function show3D(value) {
  const wasVisible = visible;
  visible = !!value && !!instance && !loading;
  stage?.classList.toggle('aura3d-live', visible);
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
  if (!canUse3D()) { updateButton('3D no compatible · Usando foto'); return; }
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
    console.warn('AURA 3D: modo 2D seguro', error);
    show3D(false);
    updateButton('No cargó 3D · Reintentar');
  }
}

function animatePresence() {
  if (!instance || !stage || !visible) return;
  // Gentle full 3D head movement, with stable eye-level framing.
  const model = instance.renderer?.model;
  if (model && originalPosition) {
    const t = performance.now() / 1000;
    const mul = prefersReduced() || !visible || document.hidden ? 0 : 1;
    const speaking = manual.active || audioPlaying || phase === 'speaking';
    model.rotation.y = originalPosition.rotationY + mul * (Math.sin(t * .57) * .024 + (speaking ? .009 : 0));
    model.rotation.x = originalPosition.rotationX + mul * Math.sin(t * .37) * .008;
    model.position.y = originalPosition.y + mul * Math.sin(t * 1.16) * .0027;
    model.position.x = originalPosition.x + mul * Math.sin(t * .45) * .002;
  }
  requestAnimationFrame(animatePresence);
}

function syncGender() {
  const next = selectedGender();
  if (!instance || gender === next) return;
  gender = next;
  instance.setAvatar(ASSETS[next]).catch(() => updateButton('No cargó el rostro · Foto 2D'));
}

function mount() {
  stage = document.getElementById('v8Stage');
  if (!stage || document.getElementById('aura3dToggle')) return;
  injectStyles();
  oldBadge = stage.querySelector('.v8-chip');
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
  stage.insertBefore(layer, stage.firstChild);

  button.addEventListener('click', async () => {
    if (loading) return;
    if (visible) {
      persist(false);
      endSpeech();
      show3D(false);
      instance?.dispose();
      instance = null;
    } else {
      persist(true);
      if (instance) show3D(true);
      else await ensureInstance();
    }
  });
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
