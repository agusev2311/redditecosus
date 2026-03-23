import { useEffect, useState } from "react";

const DEFAULT_SWATCHES = [
  "#7c3aed",
  "#8b5cf6",
  "#3b82f6",
  "#06b6d4",
  "#10b981",
  "#84cc16",
  "#f59e0b",
  "#ef4444",
  "#f472b6",
  "#f8fafc",
  "#0f172a",
];

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function normalizeHex(value, fallback = "#7c3aed") {
  const next = (value || "").trim().replace(/[^0-9a-fA-F#]/g, "");
  if (!next) {
    return fallback.toLowerCase();
  }
  const withHash = next.startsWith("#") ? next : `#${next}`;
  if (/^#([0-9a-fA-F]{3}){1,2}$/.test(withHash)) {
    return withHash.toLowerCase();
  }
  return fallback.toLowerCase();
}

function hexToRgb(value) {
  const normalized = normalizeHex(value);
  let raw = normalized.slice(1);
  if (raw.length === 3) {
    raw = raw
      .split("")
      .map((char) => `${char}${char}`)
      .join("");
  }
  return {
    r: Number.parseInt(raw.slice(0, 2), 16),
    g: Number.parseInt(raw.slice(2, 4), 16),
    b: Number.parseInt(raw.slice(4, 6), 16),
  };
}

function rgbToHex({ r, g, b }) {
  return `#${[r, g, b]
    .map((channel) => clamp(Math.round(channel), 0, 255).toString(16).padStart(2, "0"))
    .join("")}`;
}

function rgbToHsl({ r, g, b }) {
  const red = r / 255;
  const green = g / 255;
  const blue = b / 255;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  let hue = 0;
  const lightness = (max + min) / 2;
  const saturation =
    delta === 0 ? 0 : delta / (1 - Math.abs((2 * lightness) - 1));

  if (delta !== 0) {
    switch (max) {
      case red:
        hue = ((green - blue) / delta) % 6;
        break;
      case green:
        hue = (blue - red) / delta + 2;
        break;
      default:
        hue = (red - green) / delta + 4;
        break;
    }
  }

  return {
    h: Math.round((((hue * 60) + 360) % 360)),
    s: Math.round(saturation * 100),
    l: Math.round(lightness * 100),
  };
}

function hslToRgb({ h, s, l }) {
  const hue = (((h % 360) + 360) % 360) / 360;
  const saturation = clamp(s, 0, 100) / 100;
  const lightness = clamp(l, 0, 100) / 100;

  if (saturation === 0) {
    const gray = Math.round(lightness * 255);
    return { r: gray, g: gray, b: gray };
  }

  const hueToChannel = (p, q, t) => {
    let next = t;
    if (next < 0) next += 1;
    if (next > 1) next -= 1;
    if (next < 1 / 6) return p + (q - p) * 6 * next;
    if (next < 1 / 2) return q;
    if (next < 2 / 3) return p + (q - p) * ((2 / 3) - next) * 6;
    return p;
  };

  const q =
    lightness < 0.5
      ? lightness * (1 + saturation)
      : lightness + saturation - lightness * saturation;
  const p = 2 * lightness - q;

  return {
    r: Math.round(hueToChannel(p, q, hue + 1 / 3) * 255),
    g: Math.round(hueToChannel(p, q, hue) * 255),
    b: Math.round(hueToChannel(p, q, hue - 1 / 3) * 255),
  };
}

function hexToHsl(value) {
  return rgbToHsl(hexToRgb(value));
}

function hslToHex(hsl) {
  return rgbToHex(hslToRgb(hsl));
}

export default function ColorField({
  label,
  value,
  onChange,
  palette = DEFAULT_SWATCHES,
  id,
}) {
  const [draft, setDraft] = useState(value || "#7c3aed");
  const [hsl, setHsl] = useState(() => hexToHsl(value || "#7c3aed"));

  useEffect(() => {
    const next = normalizeHex(value || "#7c3aed");
    setDraft(next);
    setHsl(hexToHsl(next));
  }, [value]);

  function commit(nextValue) {
    const normalized = normalizeHex(nextValue, value || "#7c3aed");
    setDraft(normalized);
    setHsl(hexToHsl(normalized));
    onChange(normalized);
  }

  function updateHsl(partial) {
    setHsl((current) => {
      const next = {
        h: clamp(
          partial.h ?? current.h,
          0,
          360
        ),
        s: clamp(partial.s ?? current.s, 0, 100),
        l: clamp(partial.l ?? current.l, 0, 100),
      };
      const normalized = hslToHex(next);
      setDraft(normalized);
      onChange(normalized);
      return next;
    });
  }

  const previewHex = normalizeHex(value || draft);
  const saturationTrack = `linear-gradient(90deg, ${hslToHex({ h: hsl.h, s: 0, l: hsl.l })}, ${hslToHex({ h: hsl.h, s: 100, l: hsl.l })})`;
  const lightnessTrack = `linear-gradient(90deg, ${hslToHex({ h: hsl.h, s: hsl.s, l: 0 })}, ${hslToHex({ h: hsl.h, s: hsl.s, l: 50 })}, ${hslToHex({ h: hsl.h, s: hsl.s, l: 100 })})`;

  return (
    <div className="color-field">
      <div className="color-field-head">
        <span>{label}</span>
        <span className="mono">{previewHex}</span>
      </div>

      <div className="color-field-main">
        <button
          type="button"
          className="color-swatch color-swatch-large"
          style={{ "--swatch-color": previewHex }}
          onClick={() => commit(previewHex)}
          aria-label={`${label}: ${previewHex}`}
        />
        <input
          id={id}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit(draft);
            }
          }}
          placeholder="#7c3aed"
        />
      </div>

      <div className="color-field-sliders">
        <label className="color-slider">
          <span>Тон {hsl.h}°</span>
          <input
            type="range"
            min="0"
            max="360"
            value={hsl.h}
            onChange={(event) => updateHsl({ h: Number(event.target.value) })}
            style={{
              backgroundImage:
                "linear-gradient(90deg, #ff4d4d, #ffb84d, #f9f871, #51cf66, #2dd4bf, #60a5fa, #8b5cf6, #ff4d4d)",
            }}
          />
        </label>
        <label className="color-slider">
          <span>Насыщенность {hsl.s}%</span>
          <input
            type="range"
            min="0"
            max="100"
            value={hsl.s}
            onChange={(event) => updateHsl({ s: Number(event.target.value) })}
            style={{ backgroundImage: saturationTrack }}
          />
        </label>
        <label className="color-slider">
          <span>Яркость {hsl.l}%</span>
          <input
            type="range"
            min="0"
            max="100"
            value={hsl.l}
            onChange={(event) => updateHsl({ l: Number(event.target.value) })}
            style={{ backgroundImage: lightnessTrack }}
          />
        </label>
      </div>

      <div className="color-palette">
        {palette.map((color) => (
          <button
            key={`${id || label}-${color}`}
            type="button"
            className={`color-swatch ${previewHex === color.toLowerCase() ? "color-swatch-active" : ""}`}
            style={{ "--swatch-color": color }}
            onClick={() => commit(color)}
            aria-label={color}
          />
        ))}
      </div>
    </div>
  );
}
