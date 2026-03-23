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

export default function ColorField({
  label,
  value,
  onChange,
  palette = DEFAULT_SWATCHES,
  id,
}) {
  const [draft, setDraft] = useState(value || "#7c3aed");

  useEffect(() => {
    setDraft(value || "#7c3aed");
  }, [value]);

  function commit(nextValue) {
    const normalized = normalizeHex(nextValue, value || "#7c3aed");
    setDraft(normalized);
    onChange(normalized);
  }

  return (
    <div className="color-field">
      <div className="color-field-head">
        <span>{label}</span>
        <span className="mono">{normalizeHex(value || draft)}</span>
      </div>

      <div className="color-field-main">
        <button
          type="button"
          className="color-swatch color-swatch-large"
          style={{ "--swatch-color": normalizeHex(value || draft) }}
          onClick={() => commit(value || draft)}
          aria-label={`${label}: ${value || draft}`}
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

      <div className="color-palette">
        {palette.map((color) => (
          <button
            key={`${id || label}-${color}`}
            type="button"
            className={`color-swatch ${normalizeHex(value || draft) === color.toLowerCase() ? "color-swatch-active" : ""}`}
            style={{ "--swatch-color": color }}
            onClick={() => commit(color)}
            aria-label={color}
          />
        ))}
      </div>
    </div>
  );
}
