import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../api";
import MediaCard from "../components/MediaCard";
import TagBadge from "../components/TagBadge";
import { formatBytes, formatDate } from "../lib/format";

export default function LibraryPage() {
  const [items, setItems] = useState([]);
  const [tags, setTags] = useState([]);
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState("");
  const [mediaType, setMediaType] = useState("");
  const [duplicatesOnly, setDuplicatesOnly] = useState(false);
  const [tagIds, setTagIds] = useState([]);
  const [page, setPage] = useState(1);
  const [meta, setMeta] = useState({ total: 0, pages: 1 });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [shareUrl, setShareUrl] = useState("");

  const query = useMemo(() => {
    const params = new URLSearchParams({
      page: String(page),
      perPage: "24",
    });
    if (search) params.set("q", search);
    if (mediaType) params.set("mediaType", mediaType);
    if (duplicatesOnly) params.set("duplicatesOnly", "1");
    if (tagIds.length) params.set("tagIds", tagIds.join(","));
    return params.toString();
  }, [duplicatesOnly, mediaType, page, search, tagIds]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [mediaResponse, tagResponse] = await Promise.all([
        apiFetch(`/media?${query}`),
        apiFetch("/tags"),
      ]);
      if (cancelled) return;
      setItems(mediaResponse.items || []);
      setMeta({ total: mediaResponse.total, pages: mediaResponse.pages || 1 });
      setTags(tagResponse.items || []);
      const nextItems = mediaResponse.items || [];
      if (!nextItems.length) {
        setSelected(null);
        setNote("");
      } else if (!selected || !nextItems.some((item) => item.id === selected.id)) {
        setSelected(nextItems[0]);
        setNote(nextItems[0].note || "");
      }
    }
    load().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [query]);

  useEffect(() => {
    if (selected) {
      setNote(selected.note || "");
    }
  }, [selected]);

  async function saveSelected() {
    if (!selected) return;
    setBusy(true);
    try {
      const response = await apiFetch(`/media/${selected.id}`, {
        method: "PATCH",
        body: {
          note,
          tagIds: selected.tags.map((tag) => tag.id),
        },
      });
      setSelected(response.item);
      setItems((current) => current.map((item) => (item.id === response.item.id ? response.item : item)));
    } finally {
      setBusy(false);
    }
  }

  async function createShare() {
    if (!selected) return;
    const response = await apiFetch("/shares", {
      method: "POST",
      body: { mediaId: selected.id, expiresInHours: 24, burnAfterRead: true, maxViews: 1 },
    });
    setShareUrl(response.item.shareUrl);
    navigator.clipboard?.writeText(response.item.shareUrl).catch(() => undefined);
  }

  function toggleTag(tag) {
    if (!selected) return;
    const exists = selected.tags.some((item) => item.id === tag.id);
    const nextTags = exists
      ? selected.tags.filter((item) => item.id !== tag.id)
      : [...selected.tags, tag];
    setSelected((current) => ({ ...current, tags: nextTags }));
  }

  return (
    <div className="page-grid library-layout">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">search vault</p>
            <h1>Библиотека</h1>
          </div>
        </div>
        <div className="toolbar">
          <input placeholder="Поиск по имени, тегам и заметкам" value={search} onChange={(event) => setSearch(event.target.value)} />
          <select value={mediaType} onChange={(event) => setMediaType(event.target.value)}>
            <option value="">Все типы</option>
            <option value="image">Изображения</option>
            <option value="video">Видео</option>
          </select>
          <button type="button" className={`ghost-button ${duplicatesOnly ? "active-button" : ""}`} onClick={() => setDuplicatesOnly((current) => !current)}>
            Только дубликаты
          </button>
        </div>
        <div className="tag-filter-row">
          {tags.map((tag) => (
            <TagBadge
              key={tag.id}
              tag={tag}
              active={tagIds.includes(tag.id)}
              onClick={() =>
                setTagIds((current) =>
                  current.includes(tag.id) ? current.filter((id) => id !== tag.id) : [...current, tag.id]
                )
              }
            />
          ))}
        </div>
        <div className="media-grid">
          {items.map((item) => (
            <MediaCard
              key={item.id}
              item={item}
              onSelect={(next) => {
                setSelected(next);
                setShareUrl("");
              }}
            />
          ))}
        </div>
        <div className="toolbar">
          <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>
            Назад
          </button>
          <span className="muted">
            Страница {page} / {meta.pages} • всего {meta.total}
          </span>
          <button
            type="button"
            className="ghost-button"
            disabled={page >= meta.pages}
            onClick={() => setPage((current) => current + 1)}
          >
            Вперёд
          </button>
        </div>
      </section>

      <aside className="glass panel sticky-panel">
        {selected ? (
          <>
            <div className="detail-preview">
              {selected.mediaType === "video" ? (
                <video src={selected.fileUrl} controls preload="metadata" />
              ) : (
                <img src={selected.fileUrl} alt={selected.originalFilename} />
              )}
            </div>
            <h2>{selected.originalFilename}</h2>
            <p className="muted">
              {formatBytes(selected.sizeBytes)} • {formatDate(selected.createdAt)}
            </p>
            <label>
              Заметка
              <textarea rows="4" value={note} onChange={(event) => setNote(event.target.value)} />
            </label>
            <div className="tag-filter-row">
              {tags.map((tag) => (
                <TagBadge
                  key={tag.id}
                  tag={tag}
                  active={selected.tags.some((item) => item.id === tag.id)}
                  onClick={() => toggleTag(tag)}
                />
              ))}
            </div>
            <div className="button-row">
              <button type="button" className="primary-button" disabled={busy} onClick={saveSelected}>
                {busy ? "Сохраняю…" : "Сохранить"}
              </button>
              <button type="button" className="ghost-button" onClick={createShare}>
                Сгораемая ссылка
              </button>
            </div>
            {shareUrl ? <div className="success-box">Ссылка создана и скопирована: {shareUrl}</div> : null}
          </>
        ) : (
          <p className="muted">Выберите файл в библиотеке.</p>
        )}
      </aside>
    </div>
  );
}
