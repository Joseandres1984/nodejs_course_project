// AURA: small asynchronous-looking facial gestures on top of the SDK's
// existing real visemes, randomized blinks, and brow animation. Never write
// jawOpen, eyeBlink, browInnerUp, or any viseme: those belong to the lip rig.

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

  function update(renderer, { timeMs, speaking = false, reduced = false } = {}) {
    if (!renderer || !Number.isFinite(timeMs)) return { yaw: 0, pitch: 0 };
    const elapsed = lastTime === null ? 0.016 : clamp((timeMs - lastTime) / 1000, 0, .08);
    lastTime = timeMs;

    if (reduced) {
      targetX = targetY = 0;
    } else if (timeMs >= nextGlance) {
      // Don't continuously dart the eyes. Most glances are nearly central;
      // occasional small offsets last about two to four seconds.
      targetX = (random() - .5) * .16;
      targetY = (random() - .58) * .085;
      nextGlance = timeMs + 1800 + random() * 2100;
    }

    gazeX = approach(gazeX, targetX, elapsed, .42);
    gazeY = approach(gazeY, targetY, elapsed, .45);
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
      eyeSquintLeft: reduced ? 0 : (speaking ? .060 : .085),
      eyeSquintRight: reduced ? 0 : (speaking ? .060 : .085),
      cheekSquintLeft: reduced ? 0 : (speaking ? .016 : .025),
      cheekSquintRight: reduced ? 0 : (speaking ? .016 : .025),
      mouthSmileLeft: reduced ? 0 : (speaking ? .040 : .075),
      mouthSmileRight: reduced ? 0 : (speaking ? .040 : .075),
    };
    if (typeof renderer.setMorph === 'function') {
      for (const [name, value] of Object.entries(shapes)) {
        renderer.setMorph(name, value, clamp(elapsed * 6, .05, .45));
      }
    }
    return { yaw: x * .22, pitch: y * .12 };
  }

  function reset() {
    lastTime = null;
    nextGlance = 0;
    gazeX = gazeY = targetX = targetY = 0;
  }

  return { update, reset };
}
