import { useEffect, useState } from "react";

import { apiFetch } from "../api";
import TagBadge from "../components/TagBadge";

const emptyForm = {
  name: "",
  description: "",
  styleMode: "gradient",
  colorStart: "#7c3aed",
  colorEnd: "#10b981",
  textColor: "#f8fafc",
  avatarUrl: "",
};

export default function TagsPage() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);

  async function load() {
    const response = await apiFetch("/tags");
    setItems(response.items || []);
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  async function submit(event) {
    event.preventDefault();
    const response = await apiFetch(editingId ? `/tags/${editingId}` : "/tags", {
      method: editingId ? "PATCH" : "POST",
      body: form,
    });
    await load();
    setEditingId(null);
    setForm(emptyForm);
    return response;
  }

  async function remove(tagId) {
    await apiFetch(`/tags/${tagId}`, { method: "DELETE" });
    await load();
  }

  return (
    <div className="page-grid">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">tag system</p>
            <h1>Кастомные теги</h1>
          </div>
        </div>
        <div className="tag-filter-row">
          {items.map((tag) => (
            <TagBadge key={tag.id} tag={tag} />
          ))}
        </div>
        <div className="list-stack">
          {items.map((tag) => (
            <div key={tag.id} className="list-row">
              <TagBadge tag={tag} />
              <div className="button-row">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => {
                    setEditingId(tag.id);
                    setForm(tag);
                  }}
                >
                  Править
                </button>
                <button type="button" className="ghost-button danger-button" onClick={() => remove(tag.id)}>
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <form className="glass panel sticky-panel" onSubmit={submit}>
        <p className="eyebrow">designer</p>
        <h2>{editingId ? "Правка тега" : "Новый тег"}</h2>
        <label>
          Название
          <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} required />
        </label>
        <label>
          Описание
          <textarea
            rows="3"
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
          />
        </label>
        <label>
          Режим
          <select value={form.styleMode} onChange={(event) => setForm((current) => ({ ...current, styleMode: event.target.value }))}>
            <option value="gradient">Градиент</option>
            <option value="solid">Монотонный</option>
            <option value="image">С картинкой</option>
          </select>
        </label>
        <div className="field-grid">
          <label>
            Цвет 1
            <input type="color" value={form.colorStart} onChange={(event) => setForm((current) => ({ ...current, colorStart: event.target.value }))} />
          </label>
          <label>
            Цвет 2
            <input type="color" value={form.colorEnd} onChange={(event) => setForm((current) => ({ ...current, colorEnd: event.target.value }))} />
          </label>
          <label>
            Цвет текста
            <input type="color" value={form.textColor} onChange={(event) => setForm((current) => ({ ...current, textColor: event.target.value }))} />
          </label>
        </div>
        <label>
          URL аватарки
          <input value={form.avatarUrl} onChange={(event) => setForm((current) => ({ ...current, avatarUrl: event.target.value }))} />
        </label>
        <TagBadge tag={form} />
        <button className="primary-button">{editingId ? "Сохранить тег" : "Создать тег"}</button>
      </form>
    </div>
  );
}
