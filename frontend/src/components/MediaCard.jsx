import { formatBytes } from "../lib/format";

export default function MediaCard({ item, onSelect, compact = false }) {
  const Container = onSelect ? "button" : "article";
  const tagCountLabel = item.tags?.length ? `${item.tags.length} тег.` : "";

  return (
    <Container
      {...(onSelect ? { type: "button", onClick: () => onSelect(item) } : {})}
      className={`media-card ${compact ? "media-card-compact" : ""}`}
      title={item.originalFilename}
      aria-label={item.originalFilename}
    >
      <div className="media-thumb">
        {item.mediaType === "video" ? (
          <video src={item.previewUrl || item.fileUrl} muted playsInline preload="metadata" />
        ) : (
          <img src={item.previewUrl} alt={item.originalFilename} loading="lazy" />
        )}
        {item.isDuplicate ? <span className="card-badge">duplicate</span> : null}
      </div>
      <div className="media-card-overlay">
        <div className="media-card-chip-row">
          <span className="media-card-chip">{formatBytes(item.sizeBytes)}</span>
          {item.tags?.length ? <span className="media-card-chip media-card-chip-soft">{tagCountLabel}</span> : null}
        </div>
      </div>
    </Container>
  );
}
