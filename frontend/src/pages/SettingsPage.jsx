import { useEffect, useRef, useState } from "react";

import { apiFetch } from "../api";
import { formatBytes, formatDate } from "../lib/format";

export default function SettingsPage() {
  const importRef = useRef(null);
  const [settings, setSettings] = useState(null);
  const [exportsList, setExportsList] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    const [settingsResponse, exportsResponse] = await Promise.all([
      apiFetch("/admin/settings"),
      apiFetch("/admin/exports"),
    ]);
    setSettings(settingsResponse);
    setExportsList(exportsResponse.items || []);
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  async function save() {
    setBusy(true);
    try {
      await apiFetch("/admin/settings", {
        method: "PUT",
        body: settings,
      });
      setMessage("Настройки сохранены.");
    } finally {
      setBusy(false);
    }
  }

  async function exportNow(pushToTelegram) {
    await apiFetch("/admin/exports", {
      method: "POST",
      body: { pushToTelegram },
    });
    await load();
    setMessage(pushToTelegram ? "Экспорт запущен и будет отправлен в Telegram." : "Экспорт запущен.");
  }

  async function sendTelegramTest() {
    await apiFetch("/admin/telegram/test", { method: "POST" });
    setMessage("Тестовое сообщение отправлено.");
  }

  async function importArchive(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    await apiFetch("/admin/imports", { method: "POST", body: form });
    setMessage("Импорт завершён.");
    await load();
  }

  return (
    <div className="page-grid">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">server control</p>
            <h1>Сервер, экспорт и Telegram</h1>
          </div>
        </div>
        {settings ? (
          <>
            <div className="field-grid">
              <label>
                Порог диска, ГБ
                <input
                  type="number"
                  value={settings.warningGb}
                  onChange={(event) =>
                    setSettings((current) => ({ ...current, warningGb: Number(event.target.value) }))
                  }
                />
              </label>
              <label>
                Порог диска, %
                <input
                  type="number"
                  value={settings.warningPercent}
                  onChange={(event) =>
                    setSettings((current) => ({ ...current, warningPercent: Number(event.target.value) }))
                  }
                />
              </label>
              <label>
                Bot token
                <input
                  placeholder={settings.telegramBotTokenMasked || "не задан"}
                  onChange={(event) =>
                    setSettings((current) => ({ ...current, telegramBotToken: event.target.value }))
                  }
                />
              </label>
              <label>
                Chat id
                <input
                  value={settings.telegramChatId || ""}
                  onChange={(event) =>
                    setSettings((current) => ({ ...current, telegramChatId: event.target.value }))
                  }
                />
              </label>
            </div>
            <div className="button-row">
              <button type="button" className="primary-button" disabled={busy} onClick={save}>
                {busy ? "Сохраняю…" : "Сохранить настройки"}
              </button>
              <button type="button" className="ghost-button" onClick={sendTelegramTest}>
                Проверить Telegram
              </button>
            </div>
            <div className="button-row">
              <button type="button" className="ghost-button" onClick={() => exportNow(false)}>
                Экспорт
              </button>
              <button type="button" className="ghost-button" onClick={() => exportNow(true)}>
                Экспорт + Telegram
              </button>
              <button type="button" className="ghost-button" onClick={() => importRef.current?.click()}>
                Импорт
              </button>
              <input ref={importRef} hidden type="file" accept=".zip" onChange={importArchive} />
            </div>
            {message ? <div className="success-box">{message}</div> : null}
          </>
        ) : null}
      </section>

      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">exports</p>
            <h2>Архивы</h2>
          </div>
        </div>
        <div className="list-stack">
          {exportsList.map((item) => (
            <div key={item.id} className="list-row">
              <div>
                <strong>{item.id.slice(0, 8)}</strong>
                <p className="muted">
                  {item.status} • {formatDate(item.createdAt)} • {formatBytes(item.sizeBytes || 0)}
                </p>
              </div>
              {item.downloadUrl ? (
                <a className="ghost-button inline-link" href={item.downloadUrl}>
                  Скачать
                </a>
              ) : null}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
