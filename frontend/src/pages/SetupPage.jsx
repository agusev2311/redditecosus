import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../api";
import { useAuth } from "../contexts/AuthContext";

export default function SetupPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    username: "artem",
    displayName: "Artem",
    password: "",
    warningGb: 20,
    warningPercent: 10,
    telegramBotToken: "",
    telegramChatId: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiFetch("/setup/bootstrap", {
        method: "POST",
        token: "",
        body: form,
      });
      await login(form.username, form.password);
      navigate("/");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fullscreen-center">
      <form className="glass auth-card setup-card" onSubmit={submit}>
        <p className="eyebrow">first run</p>
        <h1>Первичная настройка MediaHub</h1>
        <p className="muted">
          Здесь задаётся первый админ, пороги по диску и Telegram для алертов и бэкапов.
        </p>

        <div className="field-grid">
          <label>
            Логин админа
            <input
              value={form.username}
              onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
              required
            />
          </label>
          <label>
            Отображаемое имя
            <input
              value={form.displayName}
              onChange={(event) => setForm((current) => ({ ...current, displayName: event.target.value }))}
              required
            />
          </label>
          <label>
            Пароль
            <input
              type="password"
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
              required
            />
          </label>
          <label>
            Порог диска, ГБ
            <input
              type="number"
              min="1"
              value={form.warningGb}
              onChange={(event) => setForm((current) => ({ ...current, warningGb: Number(event.target.value) }))}
            />
          </label>
          <label>
            Порог диска, %
            <input
              type="number"
              min="1"
              max="90"
              value={form.warningPercent}
              onChange={(event) =>
                setForm((current) => ({ ...current, warningPercent: Number(event.target.value) }))
              }
            />
          </label>
          <label>
            Telegram bot token
            <input
              value={form.telegramBotToken}
              onChange={(event) =>
                setForm((current) => ({ ...current, telegramBotToken: event.target.value }))
              }
            />
          </label>
          <label>
            Telegram chat id
            <input
              value={form.telegramChatId}
              onChange={(event) => setForm((current) => ({ ...current, telegramChatId: event.target.value }))}
            />
          </label>
        </div>

        {error ? <div className="error-box">{error}</div> : null}
        <button className="primary-button" disabled={busy}>
          {busy ? "Сохраняю…" : "Запустить хранилище"}
        </button>
      </form>
    </div>
  );
}
