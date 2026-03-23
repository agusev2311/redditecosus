import { useEffect, useMemo, useState } from "react";

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

const presets = [
  {
    label: "Neon",
    values: { styleMode: "gradient", colorStart: "#7c3aed", colorEnd: "#10b981", textColor: "#f8fafc" },
  },
  {
    label: "Glass",
    values: { styleMode: "solid", colorStart: "#25314b", colorEnd: "#25314b", textColor: "#f3f6ff" },
  },
  {
    label: "Signal",
    values: { styleMode: "gradient", colorStart: "#0f172a", colorEnd: "#16a34a", textColor: "#e6fff2" },
  },
];

function formFromTag(tag) {
  return {
    name: tag.name || "",
    description: tag.description || "",
    styleMode: tag.styleMode || "gradient",
    colorStart: tag.colorStart || "#7c3aed",
    colorEnd: tag.colorEnd || "#10b981",
    textColor: tag.textColor || "#f8fafc",
    avatarUrl: tag.avatarUrl || "",
  };
}

export default function TagsPage() {
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);

  async function load() {
    const response = await apiFetch("/tags");
    setItems(response.items || []);
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  const filteredItems = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) {
      return items;
    }
    return items.filter(
      (tag) =>
        tag.name.toLowerCase().includes(needle) ||
        (tag.description || "").toLowerCase().includes(needle)
    );
  }, [items, search]);

  async function submit(event) {
    event.preventDefault();
    await apiFetch(editingId ? `/tags/${editingId}` : "/tags", {
      method: editingId ? "PATCH" : "POST",
      body: form,
    });
    await load();
    setEditingId(null);
    setForm(emptyForm);
  }

  async function remove(tagId) {
    await apiFetch(`/tags/${tagId}`, { method: "DELETE" });
    await load();
    if (editingId === tagId) {
      setEditingId(null);
      setForm(emptyForm);
    }
  }

  function resetEditor() {
    setEditingId(null);
    setForm(emptyForm);
  }

  return (
    <div className="page-grid tag-studio-layout">
      <form className="glass panel sticky-panel tag-editor" onSubmit={submit}>
        <div className="section-head">
          <div>
            <p className="eyebrow">tag studio</p>
            <h1>{editingId ? "Правка тега" : "Новый тег"}</h1>
            <p className="muted">Сразу видно, как тег будет смотреться в библиотеке и разметке.</p>
          </div>
          {editingId ? (
            <button type="button" className="ghost-button" onClick={resetEditor}>
              Новый
            </button>
          ) : null}
        </div>

        <div className="tag-preview-stage">
          <TagBadge tag={form} active />
          <div className="tag-preview-caption">
            <strong>{form.name || "Ваш тег"}</strong>
            <p className="muted">{form.description || "Короткое описание или внутренняя заметка для себя."}</p>
          </div>
        </div>

        <div className="tag-preset-row">
          {presets.map((preset) => (
            <button
              key={preset.label}
              type="button"
              className="ghost-button"
              onClick={() => setForm((current) => ({ ...current, ...preset.values }))}
            >
              {preset.label}
            </button>
          ))}
        </div>

        <label>
          Название
          <input
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            required
          />
        </label>

        <label>
          Описание
          <textarea
            rows="3"
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
          />
        </label>

        <div className="tag-style-toggle">
          {[
            { value: "gradient", label: "Градиент" },
            { value: "solid", label: "Моно" },
            { value: "image", label: "Аватар" },
          ].map((mode) => (
            <button
              key={mode.value}
              type="button"
              className={`ghost-button ${form.styleMode === mode.value ? "active-button" : ""}`}
              onClick={() => setForm((current) => ({ ...current, styleMode: mode.value }))}
            >
              {mode.label}
            </button>
          ))}
        </div>

        <div className="field-grid">
          <label>
            Цвет 1
            <input
              type="color"
              value={form.colorStart}
              onChange={(event) => setForm((current) => ({ ...current, colorStart: event.target.value }))}
            />
          </label>
          <label>
            Цвет 2
            <input
              type="color"
              value={form.colorEnd}
              onChange={(event) => setForm((current) => ({ ...current, colorEnd: event.target.value }))}
            />
          </label>
          <label>
            Текст
            <input
              type="color"
              value={form.textColor}
              onChange={(event) => setForm((current) => ({ ...current, textColor: event.target.value }))}
            />
          </label>
        </div>

        <label>
          URL аватарки
          <input
            placeholder="https://..."
            value={form.avatarUrl}
            onChange={(event) => setForm((current) => ({ ...current, avatarUrl: event.target.value }))}
          />
        </label>

        <div className="button-row">
          <button className="primary-button">{editingId ? "Сохранить тег" : "Создать тег"}</button>
          <button type="button" className="ghost-button" onClick={resetEditor}>
            Сбросить
          </button>
        </div>
      </form>

      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">tag library</p>
            <h2>Все теги</h2>
          </div>
          <div className="toolbar tag-toolbar">
            <input
              placeholder="Искать теги"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
        </div>

        <div className="tag-gallery">
          {filteredItems.map((tag) => (
            <article key={tag.id} className="tag-gallery-card">
              <div className="tag-gallery-top">
                <TagBadge tag={tag} />
                <div className="tag-gallery-actions">
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => {
                      setEditingId(tag.id);
                      setForm(formFromTag(tag));
                    }}
                  >
                    Править
                  </button>
                  <button type="button" className="ghost-button danger-button" onClick={() => remove(tag.id)}>
                    Удалить
                  </button>
                </div>
              </div>
              <p className="muted">{tag.description || "Без описания, только визуальный ярлык."}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
