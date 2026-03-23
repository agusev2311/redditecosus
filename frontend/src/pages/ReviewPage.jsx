import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../api";
import TagBadge from "../components/TagBadge";
import { formatBytes } from "../lib/format";

export default function ReviewPage() {
  const [item, setItem] = useState(null);
  const [tags, setTags] = useState([]);
  const [note, setNote] = useState("");
  const [newTagName, setNewTagName] = useState("");
  const [tagSearch, setTagSearch] = useState("");
  const [saving, setSaving] = useState(false);

  async function loadNext(afterId) {
    const response = await apiFetch(`/media/review/next?untagged=1${afterId ? `&afterId=${afterId}` : ""}`);
    setItem(response.item);
    setTags(response.tags || []);
    setNote(response.item?.note || "");
  }

  useEffect(() => {
    loadNext().catch(() => undefined);
  }, []);

  const selectedTags = item?.tags || [];
  const filteredTags = useMemo(() => {
    const needle = tagSearch.trim().toLowerCase();
    const source = [...tags].sort((left, right) => left.name.localeCompare(right.name, "ru"));
    if (!needle) {
      return source;
    }
    return source.filter((tag) => tag.name.toLowerCase().includes(needle));
  }, [tagSearch, tags]);

  async function saveAndNext() {
    if (!item || saving) return;
    setSaving(true);
    try {
      await apiFetch(`/media/${item.id}`, {
        method: "PATCH",
        body: {
          note,
          tagIds: item.tags.map((tag) => tag.id),
        },
      });
      await loadNext(item.id);
    } finally {
      setSaving(false);
    }
  }

  async function skipCurrent() {
    if (!item || saving) return;
    await loadNext(item.id);
  }

  async function createQuickTag() {
    const name = newTagName.trim();
    if (!name || !item) return;
    const response = await apiFetch("/tags", {
      method: "POST",
      body: { name, styleMode: "gradient" },
    });
    setTags((current) => [...current, response.item]);
    setItem((current) => ({ ...current, tags: [...current.tags, response.item] }));
    setNewTagName("");
    setTagSearch("");
  }

  function toggleTag(tag) {
    setItem((current) => {
      if (!current) return current;
      const exists = current.tags.some((entry) => entry.id === tag.id);
      return {
        ...current,
        tags: exists ? current.tags.filter((entry) => entry.id !== tag.id) : [...current.tags, tag],
      };
    });
  }

  return (
    <div className="page-grid review-layout">
      <section className="glass panel review-stage">
        <div className="section-head">
          <div>
            <p className="eyebrow">mark mode</p>
            <h1>Быстрая разметка</h1>
            <p className="muted">Случайная выдача, крупный центрированный просмотр и один жест до следующего файла.</p>
          </div>
          {item ? (
            <div className="review-stage-head-actions">
              <div className="review-stage-stats">
                <span className="status-pill">Случайный файл</span>
                <span className="status-pill">{item.mediaType === "video" ? "Видео" : "Изображение"}</span>
                <span className="status-pill">{formatBytes(item.sizeBytes)}</span>
              </div>
              <button type="button" className="ghost-button" disabled={saving} onClick={skipCurrent}>
                Другой случайный
              </button>
            </div>
          ) : null}
        </div>

        {item ? (
          <div className="review-stage-body">
            <div className="review-media review-media-stage">
              <div className="review-media-frame">
                {item.mediaType === "video" ? (
                  <video key={item.id} src={item.fileUrl} controls preload="metadata" />
                ) : (
                  <img key={item.id} src={item.fileUrl} alt={item.originalFilename} />
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="success-box">Неразмеченных файлов сейчас нет.</div>
        )}
      </section>

      <aside className="glass panel sticky-panel review-console">
        {item ? (
          <>
            <div className="review-selected-panel">
              <div className="section-head">
                <div>
                  <p className="eyebrow">selected</p>
                  <h2>{selectedTags.length ? `${selectedTags.length} тегов выбрано` : "Выберите теги"}</h2>
                </div>
              </div>
              <div className="review-selected-tags">
                {selectedTags.length ? (
                  selectedTags.map((tag) => (
                    <TagBadge key={tag.id} tag={tag} active onClick={() => toggleTag(tag)} />
                  ))
                ) : (
                  <p className="muted">Тап по тегу добавляет его к текущему файлу. Повторный тап снимает.</p>
                )}
              </div>
            </div>

            <div className="review-quick-add">
              <input
                placeholder="Новый тег на лету"
                value={newTagName}
                onChange={(event) => setNewTagName(event.target.value)}
              />
              <button type="button" className="ghost-button" onClick={createQuickTag}>
                Создать
              </button>
            </div>

            <div className="review-tag-search">
              <input
                placeholder="Фильтр по тегам"
                value={tagSearch}
                onChange={(event) => setTagSearch(event.target.value)}
              />
            </div>

            <div className="review-tag-grid">
              {filteredTags.map((tag) => (
                <TagBadge
                  key={tag.id}
                  tag={tag}
                  active={selectedTags.some((entry) => entry.id === tag.id)}
                  onClick={() => toggleTag(tag)}
                />
              ))}
            </div>

            <label>
              Заметка
              <textarea rows="4" value={note} onChange={(event) => setNote(event.target.value)} />
            </label>

            <div className="review-action-bar">
              <button type="button" className="primary-button" disabled={saving} onClick={saveAndNext}>
                {saving ? "Сохраняю…" : "Сохранить и дальше"}
              </button>
              <button type="button" className="ghost-button" disabled={saving} onClick={skipCurrent}>
                Пропустить
              </button>
            </div>
          </>
        ) : null}
      </aside>
    </div>
  );
}
