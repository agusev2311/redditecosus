import { useEffect, useState } from "react";

import { apiFetch } from "../api";

export default function UsersPage() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ username: "", displayName: "", password: "", role: "user" });

  async function load() {
    const response = await apiFetch("/users");
    setItems(response.items || []);
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  async function create(event) {
    event.preventDefault();
    await apiFetch("/users", { method: "POST", body: form });
    setForm({ username: "", displayName: "", password: "", role: "user" });
    await load();
  }

  async function update(userId, payload) {
    await apiFetch(`/users/${userId}`, { method: "PATCH", body: payload });
    await load();
  }

  return (
    <div className="page-grid">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">access control</p>
            <h1>Пользователи</h1>
          </div>
        </div>
        <div className="list-stack">
          {items.map((item) => (
            <div key={item.id} className="list-row">
              <div>
                <strong>{item.displayName}</strong>
                <p className="muted">
                  @{item.username} • {item.role} • {item.isActive ? "active" : "disabled"}
                </p>
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

      <form className="glass panel sticky-panel" onSubmit={create}>
        <p className="eyebrow">invite</p>
        <h2>Новый пользователь</h2>
        <label>
          Логин
          <input value={form.username} onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))} required />
        </label>
        <label>
          Имя
          <input value={form.displayName} onChange={(event) => setForm((current) => ({ ...current, displayName: event.target.value }))} required />
        </label>
        <label>
          Пароль
          <input type="password" value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} required />
        </label>
        <label>
          Роль
          <select value={form.role} onChange={(event) => setForm((current) => ({ ...current, role: event.target.value }))}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <button className="primary-button">Создать пользователя</button>
      </form>
    </div>
  );
}
