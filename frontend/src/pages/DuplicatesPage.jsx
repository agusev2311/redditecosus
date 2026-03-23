import { useEffect, useState } from "react";

import { apiFetch } from "../api";
import MediaCard from "../components/MediaCard";

export default function DuplicatesPage() {
  const [groups, setGroups] = useState([]);
  const [selected, setSelected] = useState({});

  async function load() {
    const response = await apiFetch("/media/duplicates");
    setGroups(response.items || []);
    setSelected(
      Object.fromEntries(
        (response.items || []).map((group) => [
          group.sha256Hash,
          group.items.slice(1).map((item) => item.id),
        ])
      )
    );
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  async function resolveGroup(hash) {
    await apiFetch(`/media/duplicates/${hash}/resolve`, {
      method: "POST",
      body: { deleteIds: selected[hash] || [] },
    });
    await load();
  }

  return (
    <div className="page-grid">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">duplicate manager</p>
            <h1>Точные дубликаты</h1>
          </div>
        </div>
        <div className="list-stack">
          {groups.map((group) => (
            <div key={group.sha256Hash} className="duplicate-group">
              <div className="section-head">
                <div>
                  <h3>{group.count} файлов с одним hash</h3>
                  <p className="muted mono">{group.sha256Hash.slice(0, 24)}…</p>
                </div>
                <button type="button" className="ghost-button danger-button" onClick={() => resolveGroup(group.sha256Hash)}>
                  Удалить выбранные
                </button>
              </div>
              <div className="media-grid compact-grid">
                {group.items.map((item, index) => (
                  <label key={item.id} className="duplicate-card">
                    <input
                      type="checkbox"
                      checked={(selected[group.sha256Hash] || []).includes(item.id)}
                      disabled={index === 0}
                      onChange={(event) =>
                        setSelected((current) => {
                          const currentIds = current[group.sha256Hash] || [];
                          return {
                            ...current,
                            [group.sha256Hash]: event.target.checked
                              ? [...currentIds, item.id]
                              : currentIds.filter((id) => id !== item.id),
                          };
                        })
                      }
                    />
                    <MediaCard item={item} compact />
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
