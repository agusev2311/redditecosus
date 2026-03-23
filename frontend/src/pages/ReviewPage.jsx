import { useEffect, useState } from "react";

import { apiFetch } from "../api";
import TagBadge from "../components/TagBadge";

export default function ReviewPage() {
  const [item, setItem] = useState(null);
  const [tags, setTags] = useState([]);
  const [note, setNote] = useState("");
  const [newTagName, setNewTagName] = useState("");

  async function loadNext(afterId) {
    const response = await apiFetch(`/media/review/next?untagged=1${afterId ? `&afterId=${afterId}` : ""}`);
    setItem(response.item);
    setTags(response.tags || []);
    setNote(response.item?.note || "");
  }

  useEffect(() => {
    loadNext().catch(() => undefined);
  }, []);

  async function saveAndNext() {
    if (!item) return;
    await apiFetch(`/media/${item.id}`, {
      method: "PATCH",
      body: {
        note,
        tagIds: item.tags.map((tag) => tag.id),
      },
    });
    await loadNext(item.id);
  }

  async function createQuickTag() {
    if (!newTagName.trim()) return;
    const response = await apiFetch("/tags", {
      method: "POST",
      body: { name: newTagName.trim(), styleMode: "gradient" },
    });
    setTags((current) => [...current, response.item]);
    setItem((current) => ({ ...current, tags: [...current.tags, response.item] }));
    setNewTagName("");
  }

  function toggleTag(tag) {
    setItem((current) => {
      const exists = current.tags.some((entry) => entry.id === tag.id);
      return {
        ...current,
        tags: exists ? current.tags.filter((entry) => entry.id !== tag.id) : [...current.tags, tag],
      };
    });
  }

  return (
    <div className="page-grid review-layout">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">tagging mode</p>
            <h1>Поточная разметка</h1>
          </div>
        </div>
        {item ? (
          <>
            <div className="review-media">
              {item.mediaType === "video" ? (
                <video src={item.fileUrl} controls preload="metadata" />
              ) : (
                <img src={item.fileUrl} alt={item.originalFilename} />
              )}
            </div>
            <h2>{item.originalFilename}</h2>
          </>
        ) : (
          <div className="success-box">Неразмеченных файлов сейчас нет.</div>
        )}
      </section>

      <aside className="glass panel sticky-panel">
        {item ? (
          <>
            <div className="tag-filter-row">
              {tags.map((tag) => (
                <TagBadge
                  key={tag.id}
                  tag={tag}
                  active={item.tags.some((entry) => entry.id === tag.id)}
                  onClick={() => toggleTag(tag)}
                />
              ))}
            </div>
            <div className="toolbar">
              <input
                placeholder="Новый тег на лету"
                value={newTagName}
                onChange={(event) => setNewTagName(event.target.value)}
              />
              <button type="button" className="ghost-button" onClick={createQuickTag}>
                Добавить
              </button>
            </div>
            <label>
              Заметка
              <textarea rows="5" value={note} onChange={(event) => setNote(event.target.value)} />
            </label>
            <div className="button-row">
              <button type="button" className="primary-button" onClick={saveAndNext}>
                Сохранить и дальше
              </button>
              <button type="button" className="ghost-button" onClick={() => loadNext(item.id)}>
                Пропустить
              </button>
            </div>
          </>
        ) : null}
      </aside>
    </div>
  );
}
