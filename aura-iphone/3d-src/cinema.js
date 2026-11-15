/* AURA Cine: photo-faithful depth study. It deliberately does not claim to
   reconstruct a full head from one picture. The original licensed portrait
   remains the source of the skin, eyes, hair and clothing. No remote service. */
import {
  CanvasTexture, DoubleSide, Group, LinearFilter, Mesh, MeshBasicMaterial,
  OrthographicCamera, PlaneGeometry, Scene, SRGBColorSpace,
  TextureLoader, WebGLRenderer,
} from 'three';
import { createPersonalFaceGeometry } from './personal-face.js';

const FRAME = 'femenino';
const IMAGE_ASPECT = 720 / 960;
const IMAGE_HEIGHT = 2;
const IMAGE_WIDTH = IMAGE_HEIGHT * IMAGE_ASPECT;
const CAP_FPS = 30;
const IMAGE_KEYS = [0, 1, 2].map(i => `./assets/motion/${FRAME}-${i}.webp`);

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const gaussian = (x, y, rx, ry) => Math.exp(-((x / rx) ** 2 + (y / ry) ** 2) * 2);

export function faceDepthAt(u, v) {
  const top = 1 - v;
  const oval = Math.max(0, 1 - ((u - .505) / .228) ** 2 - ((top - .302) / .235) ** 2);
  const nose = gaussian(u - .503, top - .329, .052, .088);
  const cheeks = gaussian(Math.abs(u - .503) - .104, top - .338, .076, .096);
  return .005 + .047 * oval ** 1.5 + .025 * nose + .007 * cheeks;
}

// Feather the mesh around the middle of the face: the hair, ears, shoulders
// and studio backdrop stay pixel-perfect even when the head subtly moves.
export function faceFeatherAt(u, v) {
  const dx = (u - .505) / .211;
  const dy = ((1 - v) - .302) / .180;
  const radius = Math.sqrt(dx * dx + dy * dy);
  const t = clamp((1.09 - radius) / .28, 0, 1);
  return t * t * (3 - 2 * t);
}

function makeFeatherMap() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('AURA Cine: no hay Canvas 2D para la máscara facial');
  const pixels = ctx.createImageData(256, 256);
  for (let y = 0; y < 256; y++) for (let x = 0; x < 256; x++) {
    const v = 1 - y / 255; // Canvas y grows down, UV v grows up.
    const value = Math.round(255 * faceFeatherAt(x / 255, v));
    const p = (y * 256 + x) * 4;
    pixels.data[p] = pixels.data[p + 1] = pixels.data[p + 2] = value;
    pixels.data[p + 3] = 255;
  }
  ctx.putImageData(pixels, 0, 0);
  const map = new CanvasTexture(canvas);
  map.magFilter = LinearFilter;
  return map;
}

export function createCinemaAvatar({ container, imageAssets = window.AURA_ASSETS,
  onError = () => {}, personalMesh = false }) {
  const missing = IMAGE_KEYS.filter(key => !String(imageAssets?.[key] || '').startsWith('data:image/'));
  if (missing.length) throw new Error(`AURA Cine: falta retrato original (${missing.join(', ')})`);

  const scene = new Scene();
  const camera = new OrthographicCamera(-1, 1, 1, -1, .1, 10);
  camera.position.z = 3;
  const gl = new WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'low-power' });
  gl.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  Object.assign(gl.domElement.style, { width: '100%', height: '100%', display: 'block' });
  container.appendChild(gl.domElement);
  const portrait = new Group();
  const backdrop = new Group();
  scene.add(backdrop);
  scene.add(portrait);

  let disposed = false;
  let frame = 0;
  let previousTime = 0;
  let pendingFrame = 0;
  let model = null;
  let backgroundMesh = null;
  let faceRest = null;
  let eyeWeights = null;
  let lastEyePose = null;
  let lastMouthPose = -1;
  let mouthWeights = null;
  let faceMaterial = null;
  let backgroundMaterial = null;
  let alphaMap = null;
  let frames = [];
  let audio = null;
  let audioUrl = null;
  let settleAudio = null;
  let activeSpeech = false;
  const values = Object.create(null);
  let blinkStart = -1000;
  let nextBlink = 3100;

  const state = {
    model: portrait,
    setMorph(name, value) { values[name] = value; },
  };

  const avatar = {
    renderer: state,
    status: 'listening',
    frameNow() { return { visemes: {}, mode: avatar.status }; },
    setStatus(value) { avatar.status = value; },
    stopSpeaking() {
      activeSpeech = false;
      if (audio) { audio.pause(); audio.src = ''; audio = null; }
      if (settleAudio) { const resolve = settleAudio; settleAudio = null; resolve(); }
      if (audioUrl) { URL.revokeObjectURL(audioUrl); audioUrl = null; }
    },
    async speak(input) {
      avatar.stopSpeaking();
      if (disposed) throw new Error('AURA Cine: avatar cerrado');
      const body = typeof input === 'string' ? await (await fetch(input)).blob()
        : input instanceof Blob ? input : new Blob([input], { type: 'audio/wav' });
      audioUrl = URL.createObjectURL(body);
      const player = new Audio(audioUrl);
      audio = player;
      activeSpeech = true;
      try {
        await new Promise((resolve, reject) => {
          settleAudio = resolve;
          player.addEventListener('ended', resolve, { once: true });
          player.addEventListener('error', () => reject(new Error('AURA Cine: audio no disponible')), { once: true });
          player.play().catch(reject);
        });
      } finally {
        if (audio === player) avatar.stopSpeaking();
      }
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      avatar.stopSpeaking();
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      model?.geometry.dispose();
      backgroundMesh?.geometry.dispose();
      faceMaterial?.dispose();
      backgroundMaterial?.dispose();
      alphaMap?.dispose();
      for (const texture of frames) texture.dispose();
      gl.dispose();
      gl.domElement.remove();
    },
  };

  const resize = () => {
    if (disposed || !container.clientWidth || !container.clientHeight) return;
    const aspect = container.clientWidth / container.clientHeight;
    camera.left = -aspect;
    camera.right = aspect;
    camera.top = 1;
    camera.bottom = -1;
    camera.updateProjectionMatrix();
    portrait.scale.setScalar(Math.max(1, (2 * aspect) / IMAGE_WIDTH));
    backdrop.scale.copy(portrait.scale);
    // Matching static background and moving face share the same transform.
    gl.setSize(container.clientWidth, container.clientHeight, false);
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);

  function tick(timestamp) {
    if (disposed) return;
    frame = requestAnimationFrame(tick);
    if (document.hidden || timestamp - previousTime < 1000 / CAP_FPS) return;
    previousTime = timestamp;
    if (frames.length && faceMaterial) {
      const visemes = avatar.frameNow()?.visemes || {};
      const opening = Math.max(visemes.aa || 0, visemes.E || 0, visemes.I || 0,
        visemes.O || 0, visemes.U || 0, visemes.FF || 0);
      // The photographic samples are deliberately conservative: avoid the
      // exaggerated dark-mouth frame from the earlier 2D animation.
      const neuralPulse = activeSpeech ? .18 + .20 * Math.abs(Math.sin(timestamp * .012)) : 0;
      const amount = Math.max(opening, neuralPulse);
      const target = amount > .43 ? 2 : amount > .13 ? 1 : 0;
      if (target !== pendingFrame) {
        pendingFrame = target;
        faceMaterial.map = frames[target];
        faceMaterial.needsUpdate = true;
      }
      const smile = (values.mouthSmileLeft || 0) + (values.mouthSmileRight || 0);
      // At rest, the whole photo remains unchanged; the facial patch only
      // adds subtle depth. Smile movement comes from the three matched frames.
      portrait.position.z = .001 + clamp(smile, 0, .18) * .012;
      if (model && faceRest && eyeWeights) {
        const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
        if (!reduced && timestamp >= nextBlink) {
          blinkStart = timestamp;
          nextBlink = timestamp + 3300 + Math.random() * 2800;
        }
        const progress = (timestamp - blinkStart) / 190;
        const blink = reduced || progress < 0 || progress > 1 ? 0 : Math.sin(progress * Math.PI) ** 2;
        const gaze = reduced ? 0 : clamp((values.eyeLookInLeft || 0) - (values.eyeLookOutLeft || 0), -.06, .06) * .08;
        const squint = reduced ? 0 : ((values.eyeSquintLeft || 0) + (values.eyeSquintRight || 0)) * .5;
        if (!lastEyePose || Math.abs(lastEyePose.gaze - gaze) > .0001
          || Math.abs(lastEyePose.squint - squint) > .006
          || Math.abs(lastEyePose.blink - blink) > .025
          || (personalMesh && Math.abs(lastMouthPose - amount) > .025)) {
          const position = model.geometry.attributes.position;
          for (let i = 0; i < position.count; i++) {
            const eyes = eyeWeights[i];
            position.setX(i, faceRest[i * 3] + eyes * gaze);
            const restY = faceRest[i * 3 + 1];
            const eyeMovement = (restY - .484) * eyes * (.12 * squint + .64 * blink);
            // Keep the lips photographic while their landmark vertices move
            // gently with speech. A tiny asymmetric jaw motion avoids the
            // stretched, frightening smile of the old generic 3D rig.
            const mouthMovement = personalMesh && mouthWeights
              ? mouthWeights[i] * amount * (restY < .251 ? -.008 : .003)
              : 0;
            position.setY(restY - eyeMovement + mouthMovement);
          }
          position.needsUpdate = true;
          lastEyePose = { gaze, squint, blink };
          lastMouthPose = amount;
        }
      }
    }
    gl.render(scene, camera);
  }

  avatar.ready = (async () => {
    try {
      const loader = new TextureLoader();
      frames = await Promise.all(IMAGE_KEYS.map(key => loader.loadAsync(imageAssets[key])));
      if (disposed) { frames.forEach(texture => texture.dispose()); return; }
      for (const texture of frames) {
        texture.colorSpace = SRGBColorSpace;
        texture.anisotropy = Math.min(4, gl.capabilities.getMaxAnisotropy());
      }
      alphaMap = makeFeatherMap();
      backgroundMaterial = new MeshBasicMaterial({ map: frames[0], toneMapped: false });
      backgroundMesh = new Mesh(new PlaneGeometry(IMAGE_WIDTH, IMAGE_HEIGHT), backgroundMaterial);
      backgroundMesh.position.z = -.03;
      backgroundMesh.renderOrder = 0;
      backdrop.add(backgroundMesh);

      const geometry = personalMesh
        ? createPersonalFaceGeometry(IMAGE_WIDTH, IMAGE_HEIGHT)
        : new PlaneGeometry(IMAGE_WIDTH, IMAGE_HEIGHT, 78, 104);
      const points = geometry.attributes.position;
      const uv = geometry.attributes.uv;
      if (!personalMesh) {
        for (let i = 0; i < points.count; i++) {
          points.setZ(i, faceDepthAt(uv.getX(i), uv.getY(i)));
        }
      }
      points.needsUpdate = true;
      faceRest = Float32Array.from(points.array);
      eyeWeights = new Float32Array(points.count);
      mouthWeights = personalMesh ? new Float32Array(points.count) : null;
      for (let i = 0; i < points.count; i++) {
        const u = uv.getX(i), top = 1 - uv.getY(i);
        eyeWeights[i] = Math.min(1, gaussian(u - .447, top - .258, .064, .041)
          + gaussian(u - .581, top - .258, .064, .041));
        if (mouthWeights) mouthWeights[i] = gaussian(u - .54, top - .374, .086, .027);
      }
      geometry.computeVertexNormals();
      faceMaterial = new MeshBasicMaterial({
        map: frames[0], alphaMap, transparent: true,
        depthWrite: false, depthTest: !personalMesh, side: DoubleSide,
        toneMapped: false, opacity: 1,
      });
      model = new Mesh(geometry, faceMaterial);
      model.renderOrder = 1;
      portrait.add(model);
      resize();
      frame = requestAnimationFrame(tick);
    } catch (error) {
      onError(error);
      avatar.dispose();
      throw error;
    }
  })();
  return avatar;
}
