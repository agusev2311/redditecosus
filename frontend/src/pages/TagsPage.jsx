import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../api";
import TagBadge from "../components/TagBadge";
import {
  DEFAULT_GRADIENT_ANGLE,
  DEFAULT_GRADIENT_COLORS,
  MAX_GRADIENT_COLORS,
  buildGradientString,
  ensureGradientColors,
} from "../lib/tags";

const emptyForm = {
  name: "",
  description: "",
  styleMode: "gradient",
  colorStart: DEFAULT_GRADIENT_COLORS[0],
  colorEnd: DEFAULT_GRADIENT_COLORS[1],
  gradientColors: [...DEFAULT_GRADIENT_COLORS],
  gradientAngle: DEFAULT_GRADIENT_ANGLE,
  textColor: "#f8fafc",
  avatarUrl: "",
};

const presets = [
  {
    label: "Neon",
    values: {
      styleMode: "gradient",
      gradientColors: ["#7c3aed", "#3b82f6", "#10b981"],
      gradientAngle: 132,
      textColor: "#f8fafc",
    },
  },
  {
    label: "Glass",
    values: {
      styleMode: "gradient",
      gradientColors: ["#8b5cf6", "#60a5fa", "#34d399", "#bef264"],
      gradientAngle: 118,
      textColor: "#f8fafc",
    },
  },
  {
    label: "Signal",
    values: {
      styleMode: "gradient",
      gradientColors: ["#0f172a", "#14532d", "#16a34a"],
      gradientAngle: 150,
      textColor: "#e6fff2",
    },
  },
];

function syncGradientFields(nextForm) {
  const gradientColors = ensureGradientColors(nextForm);
  return {
    ...nextForm,
    gradientColors,
    colorStart: gradientColors[0],
    colorEnd: gradientColors[gradientColors.length - 1],
  };
}

function formFromTag(tag) {
  return syncGradientFields({
    name: tag.name || "",
    description: tag.description || "",
    styleMode: tag.styleMode || "gradient",
    colorStart: tag.colorStart || DEFAULT_GRADIENT_COLORS[0],
    colorEnd: tag.colorEnd || DEFAULT_GRADIENT_COLORS[1],
    gradientColors: ensureGradientColors(tag),
    gradientAngle: tag.gradientAngle ?? DEFAULT_GRADIENT_ANGLE,
    textColor: tag.textColor || "#f8fafc",
    avatarUrl: tag.avatarUrl || "",
  });
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
    const payload = syncGradientFields(form);
    await apiFetch(editingId ? `/tags/${editingId}` : "/tags", {
      method: editingId ? "PATCH" : "POST",
      body: payload,
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

  function updateForm(updater) {
    setForm((current) => syncGradientFields(typeof updater === "function" ? updater(current) : updater));
  }

  function applyPreset(preset) {
    updateForm((current) => ({ ...current, ...preset.values }));
  }

  function setGradientStop(index, value) {
    updateForm((current) => {
      const nextColors = [...current.gradientColors];
      nextColors[index] = value;
      return { ...current, gradientColors: nextColors };
    });
  }

  function addGradientStop() {
    updateForm((current) => {
      if (current.gradientColors.length >= MAX_GRADIENT_COLORS) {
        return current;
      }
      return {
        ...current,
        gradientColors: [...current.gradientColors, current.gradientColors[current.gradientColors.length - 1]],
      };
    });
  }

  function removeGradientStop(index) {
    updateForm((current) => {
      if (current.gradientColors.length <= 2) {
        return current;
      }
      return {
        ...current,
        gradientColors: current.gradientColors.filter((_, colorIndex) => colorIndex !== index),
      };
    });
  }

  return (
    <div className="page-grid tag-studio-layout">
      <form className="glass panel sticky-panel tag-editor" onSubmit={submit}>
        <div className="section-head">
          <div>
            <p className="eyebrow">tag studio</p>
            <h1>{editingId ? "Правка тега" : "Новый тег"}</h1>
            <p className="muted">Стеклянный бейдж, до 10 цветов в градиенте и точная настройка прямо на месте.</p>
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
            <p className="muted">{form.description || "Готовый бейдж сразу видно так же, как в библиотеке."}</p>
          </div>
          <div
            className="tag-gradient-bar"
            style={{
              backgroundImage: buildGradientString(form),
            }}
          />
        </div>

        <div className="tag-preset-row">
          {presets.map((preset) => (
            <button key={preset.label} type="button" className="ghost-button" onClick={() => applyPreset(preset)}>
              {preset.label}
            </button>
          ))}
        </div>

        <label>
          Название
          <input
            value={form.name}
            onChange={(event) => updateForm((current) => ({ ...current, name: event.target.value }))}
            required
          />
        </label>

        <label>
          Описание
          <textarea
            rows="3"
            value={form.description}
            onChange={(event) => updateForm((current) => ({ ...current, description: event.target.value }))}
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
              onClick={() => updateForm((current) => ({ ...current, styleMode: mode.value }))}
            >
              {mode.label}
            </button>
          ))}
        </div>

        {form.styleMode === "solid" ? (
          <div className="field-grid">
            <label>
              Основной цвет
              <input
                type="color"
                value={form.colorStart}
                onChange={(event) =>
                  updateForm((current) => ({
                    ...current,
                    colorStart: event.target.value,
                    gradientColors: [event.target.value, current.colorEnd || event.target.value],
                  }))
                }
              />
            </label>
            <label>
              Текст
              <input
                type="color"
                value={form.textColor}
                onChange={(event) => updateForm((current) => ({ ...current, textColor: event.target.value }))}
              />
            </label>
          </div>
        ) : (
          <div className="tag-gradient-editor">
            <div className="section-head tag-gradient-head">
              <div>
                <h3>Цветовые стопы</h3>
                <p className="muted">{form.gradientColors.length} / {MAX_GRADIENT_COLORS}</p>
              </div>
              <button
                type="button"
                className="ghost-button"
                disabled={form.gradientColors.length >= MAX_GRADIENT_COLORS}
                onClick={addGradientStop}
              >
                Добавить цвет
              </button>
            </div>

            <div className="tag-gradient-stop-list">
              {form.gradientColors.map((color, index) => (
                <div key={`${color}-${index}`} className="tag-gradient-stop">
                  <label>
                    Цвет {index + 1}
                    <input type="color" value={color} onChange={(event) => setGradientStop(index, event.target.value)} />
                  </label>
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={form.gradientColors.length <= 2}
                    onClick={() => removeGradientStop(index)}
                  >
                    Убрать
                  </button>
                </div>
              ))}
            </div>

            <label className="tag-angle-field">
              Угол градиента: {form.gradientAngle}°
              <input
                type="range"
                min="0"
                max="360"
                value={form.gradientAngle}
                onChange={(event) =>
                  updateForm((current) => ({ ...current, gradientAngle: Number(event.target.value) }))
                }
              />
            </label>

            <label>
              Текст
              <input
                type="color"
                value={form.textColor}
                onChange={(event) => updateForm((current) => ({ ...current, textColor: event.target.value }))}
              />
            </label>
          </div>
        )}

        <label>
          URL аватарки
          <input
            placeholder="https://..."
            value={form.avatarUrl}
            onChange={(event) => updateForm((current) => ({ ...current, avatarUrl: event.target.value }))}
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
                <div className="tag-gallery-chip-stack">
                  <TagBadge tag={tag} />
                  <p className="muted">
                    {ensureGradientColors(tag).length} цвета • угол {tag.gradientAngle ?? DEFAULT_GRADIENT_ANGLE}°
                  </p>
                </div>
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
