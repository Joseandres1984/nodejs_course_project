// Approximate Spanish visemes for iOS native speechSynthesis, which does not expose
// the rendered audio samples. Neuronal TTS audio uses the acoustic model instead.
const LETTER_MS = 76;
const REST = Object.freeze({});

function phonemeAt(text, index) {
  const pair = text.slice(index, index + 2);
  if (pair === 'ch') return ['CH', 2, 105];
  if (pair === 'll') return ['I', 2, 112];
  if (pair === 'rr') return ['RR', 2, 106];
  if (pair === 'qu') return ['kk', 2, 86];
  const c = text[index];
  if (/[.!?¿¡;:]/.test(c)) return [null, 1, 240];
  if (/[,\s]/.test(c)) return [null, 1, 86];
  if ('pbm'.includes(c)) return ['PP', 1, 96];
  if ('fv'.includes(c)) return ['FF', 1, 88];
  if ('a'.includes(c)) return ['aa', 1, 106];
  if (c === 'e') return ['E', 1, 100];
  if (c === 'i' || c === 'y') return ['I', 1, 98];
  if (c === 'o') return ['O', 1, 108];
  if (c === 'u') return ['U', 1, 110];
  if ('szx'.includes(c)) return ['SS', 1, LETTER_MS];
  if (c === 'r') return ['RR', 1, LETTER_MS];
  if ('lnñ'.includes(c)) return ['nn', 1, LETTER_MS];
  if ('ckqg'.includes(c)) return ['kk', 1, LETTER_MS];
  if (c === 'h') return [null, 1, 20];
  return ['DD', 1, LETTER_MS];
}

export function buildSpanishVisemes(text) {
  const normalized = String(text || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const segments = [];
  let elapsed = 0;
  for (let i = 0; i < normalized.length && segments.length < 2400;) {
    const [viseme, length, duration] = phonemeAt(normalized, i);
    segments.push({ viseme, start: elapsed, end: elapsed + duration });
    elapsed += duration;
    i += length;
  }
  return segments;
}

function ease(t) {
  const n = Math.min(1, Math.max(0, t));
  return n * n * (3 - 2 * n);
}

export function createSpanishLipSync(now = () => performance.now()) {
  let active = false;
  let timeline = [];
  let origin = 0;
  let audioLevel = null;

  function start(text) {
    timeline = buildSpanishVisemes(text);
    origin = now();
    audioLevel = null;
    active = true;
  }

  // Each boundary is the beginning of a word in the chunk Safari is speaking.
  // Re-anchor the local phoneme sequence so any available word markers correct drift.
  function boundary(event) {
    if (!active || !event || typeof event.text !== 'string') return;
    const offset = Math.max(0, Math.min(event.text.length, Number(event.charIndex) || 0));
    const remaining = event.text.slice(offset);
    if (!remaining) return;
    timeline = buildSpanishVisemes(remaining);
    origin = now() - 25;
  }

  function level(value) {
    if (active && Number.isFinite(Number(value))) audioLevel = Math.min(1, Math.max(0, Number(value)));
  }

  function frame() {
    if (!active || !timeline.length) return REST;
    const elapsed = now() - origin;
    const current = timeline.findIndex(segment => elapsed < segment.end + 65);
    if (current === -1) return REST;
    const result = {};
    // Slight overlap between neighbouring mouth shapes (coarticulation).
    for (let i = Math.max(0, current - 1); i <= Math.min(timeline.length - 1, current + 1); i++) {
      const s = timeline[i];
      if (!s.viseme) continue;
      const attack = ease((elapsed - (s.start - 52)) / 64);
      const release = ease(((s.end + 62) - elapsed) / 78);
      const closure = s.viseme === 'PP' || s.viseme === 'FF';
      const strength = attack * release * (closure ? .98 : .77);
      result[s.viseme] = Math.max(result[s.viseme] || 0, strength);
    }
    const closure = Math.max(result.PP || 0, result.FF || 0);
    if (closure) for (const k of ['aa', 'E', 'I', 'O', 'U']) if (result[k]) result[k] *= 1 - closure;
    if (audioLevel !== null) {
      for (const k of ['aa', 'E', 'I', 'O', 'U']) if (result[k]) result[k] *= .45 + .55 * audioLevel;
    }
    return result;
  }

  function stop() { active = false; timeline = []; audioLevel = null; }
  return { start, boundary, level, frame, stop, get active() { return active; } };
}
