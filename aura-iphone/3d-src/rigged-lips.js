// The original facial atlas is a still photograph. Large vowel/jaw morphs
// stretch its mouth corners; use a smaller articulation envelope for this
// photographic 3D face while retaining consonant closures and lip-sync.
const vowelShapes = new Set(['aa', 'E', 'I', 'O', 'U']);

export function softenRiggedVisemes(visemes) {
  if (!visemes || typeof visemes !== 'object') return {};
  const entries = Object.entries(visemes);
  if (!entries.length) return visemes;
  return Object.fromEntries(entries.map(([shape, intensity]) => {
    const strength = Number(intensity);
    if (!Number.isFinite(strength)) return [shape, 0];
    return [shape, Math.max(0, Math.min(1, strength)) * (vowelShapes.has(shape) ? .82 : .93)];
  }));
}
