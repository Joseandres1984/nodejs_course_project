// AURA: conversational microgestures on top of the SDK's visemes, blinks and
// brows. Leave jawOpen, eyeBlink, browInnerUp and every viseme to the lip rig.

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const approach = (current, target, elapsed, tau) =>
  current + (target - current) * (1 - Math.exp(-elapsed / tau));

export function createFacialPresence(random = Math.random) {
  let lastTime = null;
  let nextGlance = 0;
  let gazeX = 0;
  let gazeY = 0;
  let targetX = 0;
  let targetY = 0;
  let smile = 0;
  let smileTarget = 0;
  let nextExpression = 0;
  let nextNod = 0;
  let nodStart = -1;
  let nodDuration = 650;
  let nodStrength = 0;
  let wasSpeaking = false;

  function update(renderer, { timeMs, speaking = false, reduced = false, phase = 'ready' } = {}) {
    if (!renderer || !Number.isFinite(timeMs)) return { yaw: 0, pitch: 0, nod: 0 };
    const elapsed = lastTime === null ? 0.016 : clamp((timeMs - lastTime) / 1000, 0, .08);
    lastTime = timeMs;

    if (reduced) {
      targetX = targetY = 0;
    } else if (timeMs >= nextGlance) {
      // Hold eye contact for several seconds. Most shifts barely leave centre.
      const nearCentre = random() < .72;
      targetX = (random() - .5) * (nearCentre ? .042 : .096);
      targetY = (random() - (phase === 'thinking' ? .68 : .53)) * .056;
      nextGlance = timeMs + 3000 + random() * 2700;
    }

    if (wasSpeaking !== speaking) nextExpression = 0;
    if (!reduced && timeMs >= nextExpression) {
      smileTarget = (speaking ? .023 : .033) + random() * .021;
      nextExpression = timeMs + 2600 + random() * 3300;
    }
    smile = reduced ? 0 : approach(smile, smileTarget, elapsed, .65);

    if (speaking && !wasSpeaking) nextNod = timeMs + 300 + random() * 350;
    if (!speaking || reduced) nodStart = -1;
    else if (timeMs >= nextNod) {
      // One brief acknowledgment, with a natural pause before another.
      nodStart = timeMs;
      nodDuration = 520 + random() * 360;
      nodStrength = .006 + random() * .006;
      nextNod = timeMs + 4300 + random() * 3200;
    }
    wasSpeaking = speaking;

    const nodProgress = nodStart < 0 ? -1 : (timeMs - nodStart) / nodDuration;
    const nod = nodProgress >= 0 && nodProgress < 1
      ? nodStrength * Math.sin(nodProgress * Math.PI) ** 2 : 0;

    gazeX = approach(gazeX, targetX, elapsed, .66);
    gazeY = approach(gazeY, targetY, elapsed, .70);
    const x = reduced ? 0 : gazeX;
    const y = reduced ? 0 : gazeY;
    const right = Math.max(0, x);
    const left = Math.max(0, -x);
    const up = Math.max(0, y);
    const down = Math.max(0, -y);

    // ARKit look shapes must move both eyes the same direction, not cross them.
    const shapes = {
      eyeLookOutLeft: left,
      eyeLookInRight: left,
      eyeLookInLeft: right,
      eyeLookOutRight: right,
      eyeLookUpLeft: up,
      eyeLookUpRight: up,
      eyeLookDownLeft: down,
      eyeLookDownRight: down,
      eyeSquintLeft: reduced ? 0 : (speaking ? .055 : .070) + smile * .19,
      eyeSquintRight: reduced ? 0 : (speaking ? .055 : .070) + smile * .19,
      cheekSquintLeft: reduced ? 0 : smile * .32,
      cheekSquintRight: reduced ? 0 : smile * .32,
      mouthSmileLeft: reduced ? 0 : smile * .98,
      mouthSmileRight: reduced ? 0 : smile * 1.02,
    };
    if (typeof renderer.setMorph === 'function') {
      for (const [name, value] of Object.entries(shapes)) {
        renderer.setMorph(name, value, clamp(elapsed * 6, .05, .45));
      }
    }
    return { yaw: x * .18, pitch: y * .10, nod };
  }

  function reset() {
    lastTime = null;
    nextGlance = 0;
    gazeX = gazeY = targetX = targetY = 0;
    smile = smileTarget = 0;
    nextExpression = nextNod = 0;
    nodStart = -1;
    wasSpeaking = false;
  }

  return { update, reset };
}
