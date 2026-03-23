import { useEffect, useState } from "react";

import { apiFetch } from "../api";
import { formatBytes } from "../lib/format";

export default function UsersPage() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ username: "", displayName: "", password: "", role: "user" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function load() {
    const response = await apiFetch("/users");
    setItems(response.items || []);
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  async function create(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    const username = form.username.trim();
    const displayName = form.displayName.trim() || username;
    if (username.length < 3) {
      setError("Логин должен быть не короче 3 символов.");
      return;
    }
    if (form.password.length < 8) {
      setError("Пароль должен быть не короче 8 символов.");
      return;
    }

    setBusy(true);
    try {
      await apiFetch("/users", {
        method: "POST",
        body: {
          ...form,
          username,
          displayName,
        },
      });
      setForm({ username: "", displayName: "", password: "", role: "user" });
      setSuccess(`Пользователь @${username} создан.`);
      await load();
    } catch (createError) {
      setError(createError.message || "Не удалось создать пользователя.");
    } finally {
      setBusy(false);
    }
  }

  async function update(userId, payload) {
    setError("");
    setSuccess("");
    try {
      await apiFetch(`/users/${userId}`, { method: "PATCH", body: payload });
      await load();
    } catch (updateError) {
      setError(updateError.message || "Не удалось обновить пользователя.");
    }
  }

  return (
    <div className="page-grid users-layout">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">access control</p>
            <h1>Пользователи</h1>
          </div>
        </div>
        <div className="list-stack">
          {items.map((item) => (
            <div key={item.id} className="list-row list-row-rich">
              <div className="list-copy">
                <strong>{item.displayName}</strong>
                <p className="muted">
                  @{item.username} • {item.role} • {item.isActive ? "active" : "disabled"}
                </p>
                <div className="user-metric-strip">
                  <span className="media-card-chip">{item.mediaCount || 0} файлов</span>
                  <span className="media-card-chip">{formatBytes(item.uploadedBytes || 0)}</span>
                  <span className="media-card-chip">{item.batchCount || 0} батчей</span>
                  <span className="media-card-chip">{item.tagCount || 0} тегов</span>
                </div>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => update(item.id, { role: item.role === "admin" ? "user" : "admin" })}
                >
                  {item.role === "admin" ? "Сделать user" : "Сделать admin"}
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => update(item.id, { isActive: !item.isActive })}
                >
                  {item.isActive ? "Отключить" : "Включить"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <form className="glass panel sticky-panel user-create-panel" onSubmit={create}>
        <p className="eyebrow">invite</p>
        <h2>Новый пользователь</h2>
        {success ? <div className="success-box">{success}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}
        <label>
          Логин
          <input
            value={form.username}
            minLength={3}
            onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
            required
          />
        </label>
        <label>
          Имя
          <input
            value={form.displayName}
            placeholder="Если пусто, возьмётся логин"
            onChange={(event) => setForm((current) => ({ ...current, displayName: event.target.value }))}
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            minLength={8}
            value={form.password}
            onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
            required
          />
        </label>
        <label>
          Роль
          <select value={form.role} onChange={(event) => setForm((current) => ({ ...current, role: event.target.value }))}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <p className="muted">Логин: минимум 3 символа. Пароль: минимум 8 символов.</p>
        <button className="primary-button" disabled={busy}>
          {busy ? "Создаю…" : "Создать пользователя"}
        </button>
      </form>
    </div>
  );
}
