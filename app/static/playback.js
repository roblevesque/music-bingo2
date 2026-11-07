// Small pure helpers for the host console's audio playback (no DOM, easy to reason about).

/** Number from a text box, kept inside [min, max]; `fallback` if it isn't a number. */
export function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (value === "" || !Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

/**
 * Volume (0..1) for a point in a clip's play window: ramps up over `fade` seconds
 * from `start` and down over `fade` seconds to `end`. `end` may be unknown (NaN or
 * Infinity), in which case there is no fade-out. If the window is shorter than two
 * fades, each fade shrinks to half the window so they never overlap into silence.
 */
export function fadeVolume(time, start, end, fade) {
  if (!(fade > 0)) return 1;
  const known = Number.isFinite(end);
  const length = known ? Math.max(0, end - start) : Infinity;
  const f = known ? Math.min(fade, length / 2) : fade;
  if (!(f > 0)) return 1;
  const rising = (time - start) / f;
  const falling = known ? (end - time) / f : 1;
  return Math.min(1, Math.max(0, Math.min(rising, falling)));
}
