export default function TagBadge({ tag, active = false, onClick }) {
  const style =
    tag.styleMode === "solid"
      ? {
          background: tag.colorStart,
          color: tag.textColor,
        }
      : {
          background:
            tag.styleMode === "image" && tag.avatarUrl
              ? `linear-gradient(135deg, ${tag.colorStart}, ${tag.colorEnd}), url(${tag.avatarUrl}) center/cover`
              : `linear-gradient(135deg, ${tag.colorStart}, ${tag.colorEnd})`,
          color: tag.textColor,
        };

  return (
    <button
      type="button"
      className={`tag-badge ${active ? "tag-badge-active" : ""}`}
      style={style}
      onClick={onClick}
    >
      {tag.avatarUrl ? <span className="tag-avatar" style={{ backgroundImage: `url(${tag.avatarUrl})` }} /> : null}
      <span>{tag.name}</span>
    </button>
  );
}
