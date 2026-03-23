import { useEffect, useMemo, useState } from "react";

import { apiFetch, getStoredToken, uploadFileWithProgress } from "../api";
import ColorField from "../components/ColorField";
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
  avatarSourceValue: "",
  avatarSourceType: "none",
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
    avatarSourceValue: tag.avatarSourceValue || tag.avatarUrl || "",
    avatarSourceType: tag.avatarSourceType || "external",
  });
}

export default function TagsPage() {
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [mediaSearch, setMediaSearch] = useState("");
  const [mediaItems, setMediaItems] = useState([]);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarProgress, setAvatarProgress] = useState(0);

  async function load() {
    const response = await apiFetch("/tags");
    setItems(response.items || []);
  }

  async function loadMedia(query = "") {
    const params = new URLSearchParams({
      mediaType: "image",
      perPage: "18",
    });
    if (query.trim()) {
      params.set("q", query.trim());
    }
    const response = await apiFetch(`/media?${params.toString()}`);
    setMediaItems(response.items || []);
  }

  useEffect(() => {
    load().catch(() => undefined);
    loadMedia().catch(() => undefined);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadMedia(mediaSearch).catch(() => undefined);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [mediaSearch]);

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
    const payload = syncGradientFields({
      ...form,
      avatarUrl: form.avatarSourceValue || "",
    });
    await apiFetch(editingId ? `/tags/${editingId}` : "/tags", {
      method: editingId ? "PATCH" : "POST",
      body: payload,
    });
    await load();
    setEditingId(null);
    setForm(emptyForm);
    setAvatarProgress(0);
  }

  async function remove(tagId) {
    await apiFetch(`/tags/${tagId}`, { method: "DELETE" });
    await load();
    if (editingId === tagId) {
      setEditingId(null);
      setForm(emptyForm);
      setAvatarProgress(0);
    }
  }

  function resetEditor() {
    setEditingId(null);
    setForm(emptyForm);
    setAvatarProgress(0);
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

  function setExternalAvatar(value) {
    updateForm((current) => ({
      ...current,
      avatarSourceType: value.trim() ? "external" : "none",
      avatarSourceValue: value.trim(),
      avatarUrl: value.trim(),
    }));
  }

  function chooseMediaAvatar(item) {
    updateForm((current) => ({
      ...current,
      avatarSourceType: "media",
      avatarSourceValue: `media:${item.id}`,
      avatarUrl: item.previewUrl || item.fileUrl,
    }));
  }

  async function uploadAvatarFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setAvatarBusy(true);
    setAvatarProgress(0);
    try {
      const response = await uploadFileWithProgress("/tags/avatar-upload", file, {
        token: getStoredToken(),
        onProgress: (loaded, total) => {
          if (!total) return;
          setAvatarProgress((loaded / total) * 100);
        },
      });
      updateForm((current) => ({
        ...current,
        avatarSourceType: "upload",
        avatarSourceValue: response.avatarRef,
        avatarUrl: response.avatarUrl,
      }));
    } finally {
      setAvatarBusy(false);
      event.target.value = "";
    }
  }

  return (
    <div className="page-grid tag-studio-layout">
      <form className="glass panel sticky-panel tag-editor" onSubmit={submit}>
        <div className="section-head">
          <div>
            <p className="eyebrow">tag studio</p>
            <h1>{editingId ? "Правка тега" : "Новый тег"}</h1>
            <p className="muted">Свой color picker, стеклянный градиент и аватарка из файла или вашей коллекции.</p>
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
          <div className="tag-gradient-bar" style={{ backgroundImage: buildGradientString(form) }} />
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
            <ColorField
              label="Основной цвет"
              value={form.colorStart}
              onChange={(value) =>
                updateForm((current) => ({
                  ...current,
                  colorStart: value,
                  gradientColors: [value, current.colorEnd || value],
                }))
              }
              id="tag-solid-color"
            />
            <ColorField
              label="Текст"
              value={form.textColor}
              onChange={(value) => updateForm((current) => ({ ...current, textColor: value }))}
              id="tag-solid-text"
            />
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
                <div key={`${index}-${color}`} className="tag-gradient-stop">
                  <ColorField
                    label={`Цвет ${index + 1}`}
                    value={color}
                    onChange={(value) => setGradientStop(index, value)}
                    id={`tag-color-stop-${index}`}
                  />
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

            <ColorField
              label="Текст"
              value={form.textColor}
              onChange={(value) => updateForm((current) => ({ ...current, textColor: value }))}
              id="tag-text-color"
            />
          </div>
        )}

        <div className="tag-avatar-editor">
          <div className="section-head tag-gradient-head">
            <div>
              <h3>Аватарка тега</h3>
              <p className="muted">Можно вставить URL, загрузить файл или взять картинку из своей медиатеки.</p>
            </div>
          </div>

          <label>
            Внешний URL
            <input
              placeholder="https://..."
              value={form.avatarSourceType === "external" ? form.avatarSourceValue : ""}
              onChange={(event) => setExternalAvatar(event.target.value)}
            />
          </label>

          <div className="tag-avatar-upload-row">
            <label className="ghost-button tag-upload-button">
              {avatarBusy ? `Загрузка ${Math.round(avatarProgress)}%` : "Загрузить файл"}
              <input hidden type="file" accept="image/*" onChange={uploadAvatarFile} />
            </label>
            <button
              type="button"
              className="ghost-button"
              onClick={() =>
                updateForm((current) => ({
                  ...current,
                  avatarSourceType: "none",
                  avatarSourceValue: "",
                  avatarUrl: "",
                }))
              }
            >
              Очистить
            </button>
          </div>

          <div className="tag-media-picker">
            <div className="toolbar tag-toolbar">
              <input
                placeholder="Искать картинку в своей библиотеке"
                value={mediaSearch}
                onChange={(event) => setMediaSearch(event.target.value)}
              />
            </div>

            <div className="tag-media-grid">
              {mediaItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`tag-media-card ${form.avatarSourceValue === `media:${item.id}` ? "tag-media-card-active" : ""}`}
                  onClick={() => chooseMediaAvatar(item)}
                >
                  <img src={item.previewUrl || item.fileUrl} alt={item.originalFilename} loading="lazy" />
                </button>
              ))}
            </div>
          </div>
        </div>

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
            <input placeholder="Искать теги" value={search} onChange={(event) => setSearch(event.target.value)} />
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
