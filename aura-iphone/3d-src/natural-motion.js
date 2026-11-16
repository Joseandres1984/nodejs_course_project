// Head posture for the articulated avatar. Human attention is mostly still:
// short, irregular shifts with a gentle settle, not continuous sine waves.
// Pure state, so mobile Safari needs no extra timers or animation loops.
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const ease = (value, target, seconds, timeConstant) =>
  value + (target - value) * (1 - Math.exp(-seconds / timeConstant));
const neutral = () => ({ yaw: 0, pitch: 0, roll: 0, lift: 0, shift: 0 });

export function createNaturalMotion(random = Math.random) {
  let pose = neutral();
  let target = neutral();
  let lastTime = null;
  let nextShift = 0;
  let wasSpeaking = false;

  function reset() {
    pose = neutral();
    target = neutral();
    lastTime = null;
    nextShift = 0;
    wasSpeaking = false;
  }

  function update({ timeMs, speaking = false, phase = 'ready', reduced = false, hidden = false,
    eyeYaw = 0, eyePitch = 0, speechNod = 0 } = {}) {
    if (!Number.isFinite(timeMs)) return neutral();
    if (reduced || hidden) {
      reset();
      return neutral();
    }

    if (lastTime === null) {
      lastTime = timeMs;
      // Begin with steady eye contact instead of moving at first paint.
      nextShift = timeMs + 1600 + random() * 2800;
    }
    // Guard against enormous time steps after iOS backgrounds Safari.
    const dt = clamp((timeMs - lastTime) / 1000, 0, .055);
    lastTime = timeMs;

    // An interaction starts with a slight change in attention, not a nod loop.
    if (speaking !== wasSpeaking) {
      nextShift = Math.min(nextShift, timeMs + (speaking ? 140 : 700));
      wasSpeaking = speaking;
    }

    if (timeMs >= nextShift) {
      // Long periods of eye contact and a few barely perceptible glances.
      const quiet = random() < (speaking ? .39 : .62);
      const amplitude = quiet ? .30 : 1;
      const thinking = phase === 'thinking';
      target = {
        yaw: (random() - .5) * .027 * amplitude,
        pitch: (random() - (thinking ? .38 : .51)) * .013 * amplitude,
        roll: (random() - .5) * .006 * amplitude,
        lift: (random() - .5) * .0014 * amplitude,
        shift: (random() - .5) * .0012 * amplitude,
      };
      // Durations vary substantially. No fixed angular frequency.
      nextShift = timeMs + (speaking ? 2500 : 4300) + random() * (speaking ? 3600 : 5100);
    }

    // Different response times make the head settle rather than move on rails.
    pose.yaw = ease(pose.yaw, target.yaw, dt, .65);
    pose.pitch = ease(pose.pitch, target.pitch, dt, .82);
    pose.roll = ease(pose.roll, target.roll, dt, 1.15);
    pose.lift = ease(pose.lift, target.lift, dt, 1.6);
    pose.shift = ease(pose.shift, target.shift, dt, 1.3);

    // Eyes lead the head a little. The speech rig supplies occasional brief
    // nods; never synthesize another periodic one on top of those nods.
    return {
      yaw: clamp(pose.yaw + eyeYaw * .19, -.021, .021),
      pitch: clamp(pose.pitch + eyePitch * .16 + speechNod, -.013, .023),
      roll: pose.roll,
      lift: pose.lift,
      shift: pose.shift,
    };
  }

  return { update, reset };
}
