import { formatBytes } from "../lib/format";
import TagBadge from "./TagBadge";

export default function MediaCard({ item, onSelect, compact = false }) {
  return (
    <button type="button" className={`media-card ${compact ? "media-card-compact" : ""}`} onClick={() => onSelect?.(item)}>
      <div className="media-thumb">
        {item.mediaType === "video" ? (
          <video src={item.previewUrl || item.fileUrl} muted playsInline preload="metadata" />
        ) : (
          <img src={item.previewUrl} alt={item.originalFilename} loading="lazy" />
        )}
        {item.isDuplicate ? <span className="card-badge">duplicate</span> : null}
      </div>
      <div className="media-card-body">
        <strong title={item.originalFilename}>{item.originalFilename}</strong>
        <span>{formatBytes(item.sizeBytes)}</span>
        <div className="tag-row">
          {item.tags.slice(0, 3).map((tag) => (
            <TagBadge key={tag.id} tag={tag} />
          ))}
        </div>
      </div>
    </button>
  );
}
