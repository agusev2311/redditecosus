import { useMemo, useRef, useState } from "react";

import { apiFetch, getStoredToken, uploadFileWithProgress } from "../api";
import { formatBytes, formatDuration, formatRate } from "../lib/format";

export default function UploadPage() {
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [session, setSession] = useState(null);
  const [queue, setQueue] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const totals = useMemo(() => {
    const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
    return {
      totalBytes,
      totalFiles: files.length,
    };
  }, [files]);

  function attachFiles(list) {
    const nextFiles = Array.from(list || []);
    setFiles(nextFiles);
    setQueue(
      nextFiles.map((file) => ({
        name: file.name,
        size: file.size,
        progress: 0,
        status: "queued",
      }))
    );
  }

  async function startUpload() {
    if (!files.length) return;
    setBusy(true);
    setError("");
    const startedAt = Date.now();
    let transferred = 0;

    try {
      const sessionResponse = await apiFetch("/uploads", {
        method: "POST",
        body: {
          clientTotalFiles: totals.totalFiles,
          totalBytes: totals.totalBytes,
        },
      });
      const createdSession = sessionResponse.item;
      setSession(createdSession);

      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        setQueue((current) =>
          current.map((entry, entryIndex) =>
            entryIndex === index ? { ...entry, status: "uploading" } : entry
          )
        );

        await uploadFileWithProgress(`/uploads/${createdSession.id}/files`, file, {
          token: getStoredToken(),
          onProgress: (loaded, total) => {
            const overall = transferred + loaded;
            const elapsed = Math.max((Date.now() - startedAt) / 1000, 1);
            const speed = overall / elapsed;
            const eta = speed ? (totals.totalBytes - overall) / speed : 0;
            setQueue((current) =>
              current.map((entry, entryIndex) =>
                entryIndex === index
                  ? {
                      ...entry,
                      progress: total ? loaded / total : 0,
                      status: "uploading",
                      speed,
                      eta,
                    }
                  : entry
              )
            );
          },
        });

        transferred += file.size;
        setQueue((current) =>
          current.map((entry, entryIndex) =>
            entryIndex === index ? { ...entry, progress: 1, status: "uploaded" } : entry
          )
        );
      }

      const commit = await apiFetch(`/uploads/${createdSession.id}/commit`, { method: "POST" });
      setSession(commit.item);

      const poll = window.setInterval(async () => {
        const status = await apiFetch(`/uploads/${createdSession.id}`);
        setSession(status.item);
        if (["completed", "completed_with_warnings", "failed"].includes(status.item.status)) {
          window.clearInterval(poll);
        }
      }, 1500);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">bulk uploader</p>
            <h1>Массовая загрузка файлов и архивов</h1>
          </div>
        </div>
        <div
          className="dropzone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            attachFiles(event.dataTransfer.files);
          }}
        >
          <input
            ref={inputRef}
            type="file"
            hidden
            multiple
            accept="image/*,video/*,.zip,.tar,.gz,.tgz"
            onChange={(event) => attachFiles(event.target.files)}
          />
          <h3>Перетаскивайте пачки файлов сюда</h3>
          <p className="muted">Можно сразу фотографии, видео и zip/tar архивы.</p>
          <div className="button-row">
            <button type="button" className="primary-button" onClick={() => inputRef.current?.click()}>
              Выбрать файлы
            </button>
            <button type="button" className="ghost-button" disabled={!files.length || busy} onClick={startUpload}>
              {busy ? "Загрузка…" : "Начать импорт"}
            </button>
          </div>
        </div>
        <div className="stats-grid">
          <div className="stat-card">
            <span>Файлов</span>
            <strong>{totals.totalFiles}</strong>
          </div>
          <div className="stat-card">
            <span>Всего веса</span>
            <strong>{formatBytes(totals.totalBytes)}</strong>
          </div>
          <div className="stat-card">
            <span>Батч</span>
            <strong>{session ? session.id.slice(0, 8) : "—"}</strong>
          </div>
        </div>
        {session ? (
          <div className="panel-block">
            <h3>Серверная обработка</h3>
            <p>
              Статус: <strong>{session.status}</strong>
            </p>
            <p>
              Обработано: {session.processedItems}/{session.totalItems || "?"}
            </p>
            <p>
              Сохранено: {session.storedItems}, дубликатов: {session.duplicateItems}, ошибок: {session.failedItems}
            </p>
          </div>
        ) : null}
        {error ? <div className="error-box">{error}</div> : null}
      </section>

      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">live progress</p>
            <h2>Очередь</h2>
          </div>
        </div>
        <div className="list-stack">
          {queue.map((entry, index) => (
            <div key={`${entry.name}-${index}`} className="queue-row">
              <div>
                <strong>{entry.name}</strong>
                <p className="muted">
                  {formatBytes(entry.size)} • {entry.status}
                </p>
                {entry.speed ? (
                  <p className="muted">
                    {formatRate(entry.speed)} • осталось {formatDuration(entry.eta)}
                  </p>
                ) : null}
              </div>
              <div className="queue-progress">
                <div className="metric-track">
                  <div className="metric-fill" style={{ width: `${(entry.progress || 0) * 100}%` }} />
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
