const DEFAULT_GRADIENT_COLORS = ["#7c3aed", "#10b981"];
const DEFAULT_GRADIENT_ANGLE = 135;
const MAX_GRADIENT_COLORS = 10;

export function ensureGradientColors(tag = {}) {
  const raw = Array.isArray(tag.gradientColors) ? tag.gradientColors : [];
  const colors = raw.filter(Boolean).slice(0, MAX_GRADIENT_COLORS);
  if (colors.length >= 2) {
    return colors;
  }

  const fallback = [tag.colorStart || DEFAULT_GRADIENT_COLORS[0], tag.colorEnd || DEFAULT_GRADIENT_COLORS[1]];
  if (colors.length === 1) {
    return [colors[0], fallback[1]];
  }
  return fallback;
}

export function ensureGradientAngle(tag = {}) {
  const numeric = Number(tag.gradientAngle);
  if (Number.isFinite(numeric)) {
    return Math.max(0, Math.min(360, Math.round(numeric)));
  }
  return DEFAULT_GRADIENT_ANGLE;
}

export function buildGradientString(tag = {}) {
  return `linear-gradient(${ensureGradientAngle(tag)}deg, ${ensureGradientColors(tag).join(", ")})`;
}

export { DEFAULT_GRADIENT_ANGLE, DEFAULT_GRADIENT_COLORS, MAX_GRADIENT_COLORS };
