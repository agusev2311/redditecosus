import { buildGradientString, ensureGradientColors } from "../lib/tags";

export default function TagBadge({ tag, active = false, onClick }) {
  const gradientColors = ensureGradientColors(tag);
  const gradient = buildGradientString(tag);
  const style = {
    "--tag-base": tag.styleMode === "solid" ? tag.colorStart || gradientColors[0] : "var(--surface-2)",
    "--tag-gradient":
      tag.styleMode === "solid"
        ? "none"
        : tag.styleMode === "image" && tag.avatarUrl
          ? `${gradient}, url(${tag.avatarUrl})`
          : gradient,
    "--tag-text": tag.textColor || "#f8fafc",
    "--tag-border": active ? "color-mix(in srgb, var(--text) 24%, transparent)" : "var(--line)",
  };
  const className = `tag-badge ${active ? "tag-badge-active" : ""}`;
  const content = (
    <span className="tag-badge-content">
      {tag.avatarUrl ? <span className="tag-avatar" style={{ backgroundImage: `url(${tag.avatarUrl})` }} /> : null}
      <span>{tag.name}</span>
    </span>
  );

  if (!onClick) {
    return (
      <span className={className} style={style}>
        {content}
      </span>
    );
  }

  return (
    <button type="button" className={className} style={style} onClick={onClick}>
      {content}
    </button>
  );
}
