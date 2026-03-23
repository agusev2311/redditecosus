import { useEffect, useState } from "react";

import { apiFetch } from "../api";
import MediaCard from "../components/MediaCard";

const DEFAULT_THRESHOLD = 88;

export default function DuplicatesPage() {
  const [groups, setGroups] = useState([]);
  const [selected, setSelected] = useState({});
  const [mode, setMode] = useState("exact");
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);

  async function load() {
    const params = new URLSearchParams({ mode });
    if (mode === "similar") {
      params.set("threshold", String(threshold));
    }
    const response = await apiFetch(`/media/duplicates?${params.toString()}`);
    const items = response.items || [];
    setGroups(items);
    setSelected(
      Object.fromEntries(items.map((group) => [group.key, group.items.slice(1).map((item) => item.id)]))
    );
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, [mode, threshold]);

  async function resolveGroup(groupKey) {
    await apiFetch("/media/duplicates/resolve", {
      method: "POST",
      body: { deleteIds: selected[groupKey] || [] },
    });
    await load();
  }

  return (
    <div className="page-grid">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">duplicate manager</p>
            <h1>{mode === "exact" ? "Точные дубликаты" : "Похожие изображения"}</h1>
            <p className="muted">
              {mode === "exact"
                ? "Одинаковые файлы по sha256."
                : "Поиск похожих картинок по визуальному отпечатку, даже если качество или размер сжались."}
            </p>
          </div>
          <div className="duplicate-toolbar">
            <div className="duplicate-mode-toggle">
              <button
                type="button"
                className={`ghost-button ${mode === "exact" ? "active-button" : ""}`}
                onClick={() => setMode("exact")}
              >
                По hash
              </button>
              <button
                type="button"
                className={`ghost-button ${mode === "similar" ? "active-button" : ""}`}
                onClick={() => setMode("similar")}
              >
                По сходству
              </button>
            </div>
            {mode === "similar" ? (
              <label className="duplicate-threshold-field">
                Порог сходства: {threshold}%
                <input
                  type="range"
                  min="70"
                  max="99"
                  value={threshold}
                  onChange={(event) => setThreshold(Number(event.target.value))}
                />
              </label>
            ) : null}
          </div>
        </div>

        <div className="list-stack">
          {groups.map((group) => (
            <div key={group.key} className="duplicate-group">
              <div className="section-head">
                <div>
                  <h3>
                    {group.mode === "exact"
                      ? `${group.count} файлов с одним hash`
                      : `${group.count} визуально похожих файлов`}
                  </h3>
                  <p className="muted mono">
                    {group.mode === "exact"
                      ? `${group.sha256Hash.slice(0, 24)}…`
                      : `Средняя похожесть: ${group.similarityPercent}%`}
                  </p>
                </div>
                <button type="button" className="ghost-button danger-button" onClick={() => resolveGroup(group.key)}>
                  Удалить выбранные
                </button>
              </div>

              <div className="media-grid compact-grid duplicate-grid">
                {group.items.map((item, index) => (
                  <label key={item.id} className="duplicate-card">
                    <input
                      type="checkbox"
                      checked={(selected[group.key] || []).includes(item.id)}
                      disabled={index === 0}
                      onChange={(event) =>
                        setSelected((current) => {
                          const currentIds = current[group.key] || [];
                          return {
                            ...current,
                            [group.key]: event.target.checked
                              ? [...currentIds, item.id]
                              : currentIds.filter((id) => id !== item.id),
                          };
                        })
                      }
                    />
                    <MediaCard item={item} compact />
                    <div className="duplicate-card-copy">
                      <strong>{index === 0 ? "Оставить" : "К удалению"}</strong>
                      <span className="muted">
                        {group.mode === "exact" ? "Hash 100%" : `Сходство ${item.matchPercent}%`}
                      </span>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          ))}

          {!groups.length ? <div className="success-box">Подходящих дубликатов по текущему режиму пока не найдено.</div> : null}
        </div>
      </section>
    </div>
  );
}
