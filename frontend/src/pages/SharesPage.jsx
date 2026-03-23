import { useEffect, useState } from "react";

import { apiFetch } from "../api";
import { formatDate } from "../lib/format";

export default function SharesPage() {
  const [items, setItems] = useState([]);

  async function load() {
    const response = await apiFetch("/shares");
    setItems(response.items || []);
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  async function revoke(shareId) {
    await apiFetch(`/shares/${shareId}/revoke`, { method: "POST" });
    await load();
  }

  return (
    <div className="page-grid">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">burn after read</p>
            <h1>Временные ссылки</h1>
          </div>
        </div>
        <div className="list-stack">
          {items.map((item) => (
            <div key={item.id} className="list-row">
              <div>
                <strong>{item.media?.originalFilename}</strong>
                <p className="muted">
                  {formatDate(item.createdAt)} • просмотров {item.viewCount}/{item.maxViews ?? "∞"}
                </p>
                <a href={item.shareUrl} target="_blank" rel="noreferrer">
                  {item.shareUrl}
                </a>
              </div>
              <button type="button" className="ghost-button danger-button" onClick={() => revoke(item.id)}>
                Отозвать
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
