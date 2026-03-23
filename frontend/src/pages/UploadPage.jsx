import { useEffect, useMemo, useRef, useState } from "react";

import { apiFetch, getStoredToken, uploadBinaryChunk } from "../api";
import { formatBytes, formatDuration, formatRate } from "../lib/format";

const DRAFT_KEY = "mediahub_upload_draft_v2";
const DEFAULT_CHUNK_SIZE = 16 * 1024 * 1024;
const DRAFT_SYNC_DELAY_MS = 800;
const PROGRESS_REFRESH_MS = 120;

function pickChunkSize(fileSize, preferredChunkSize) {
  const base = Math.max(preferredChunkSize || DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_SIZE);
  if (fileSize >= 1024 * 1024 * 1024) {
    return Math.max(base, 32 * 1024 * 1024);
  }
  if (fileSize >= 256 * 1024 * 1024) {
    return Math.max(base, 24 * 1024 * 1024);
  }
  return base;
}

function fileSignature(file) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function readDraft() {
  try {
    return JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
  } catch {
    return null;
  }
}

function writeDraft(draft) {
  if (!draft) {
    localStorage.removeItem(DRAFT_KEY);
    return;
  }
  localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
}

function sameSignatureSet(files, draft) {
  if (!draft?.fileKeys?.length) return false;
  const current = files.map((file) => fileSignature(file)).sort();
  const saved = [...draft.fileKeys].sort();
  return current.length === saved.length && current.every((value, index) => value === saved[index]);
}

function queueFromFiles(files, draft, preferredChunkSize = DEFAULT_CHUNK_SIZE) {
  return files.map((file) => {
    const signature = fileSignature(file);
    const saved = draft?.files?.[signature];
    const uploadedBytes = Math.min(saved?.uploadedBytes || 0, file.size);
    return {
      signature,
      file,
      name: file.name,
      size: file.size,
      fileId: saved?.fileId || null,
      uploadedBytes,
      progress: file.size ? uploadedBytes / file.size : 0,
      status: saved ? saved.status || "paused" : "queued",
      chunkSize: saved?.chunkSize || pickChunkSize(file.size, preferredChunkSize),
      error: saved?.error || "",
    };
  });
}

function toDraft(batchId, queue) {
  return {
    batchId,
    fileKeys: queue.map((entry) => entry.signature),
    files: Object.fromEntries(
      queue.map((entry) => [
        entry.signature,
        {
          name: entry.name,
          size: entry.size,
          fileId: entry.fileId,
          uploadedBytes: entry.uploadedBytes,
          chunkSize: entry.chunkSize,
          status: entry.status,
          error: entry.error || "",
        },
      ])
    ),
  };
}

export default function UploadPage() {
  const inputRef = useRef(null);
  const resumeOnReconnectRef = useRef(false);
  const sessionIdRef = useRef(readDraft()?.batchId || null);
  const startUploadRef = useRef(null);
  const queueRef = useRef([]);
  const draftSyncTimeoutRef = useRef(null);
  const lastProgressUpdateRef = useRef(0);
  const [files, setFiles] = useState([]);
  const [session, setSession] = useState(null);
  const [queue, setQueue] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [networkMessage, setNetworkMessage] = useState("");
  const [resumeDraft, setResumeDraft] = useState(readDraft());
  const [telemetry, setTelemetry] = useState({ speed: 0, eta: 0 });
  const [startedAt, setStartedAt] = useState(null);
  const [preferredChunkSize, setPreferredChunkSize] = useState(DEFAULT_CHUNK_SIZE);

  const totals = useMemo(() => {
    const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
    const uploadedBytes = queue.reduce((sum, entry) => sum + (entry.uploadedBytes || 0), 0);
    return {
      totalBytes,
      uploadedBytes,
      totalFiles: files.length,
    };
  }, [files, queue]);

  useEffect(() => {
    apiFetch("", { token: "" })
      .then((response) => {
        const recommendedChunkSize = Number(response.recommendedUploadChunkBytes || 0);
        if (recommendedChunkSize > 0) {
          setPreferredChunkSize(recommendedChunkSize);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const draft = readDraft();
    setResumeDraft(draft);
    sessionIdRef.current = draft?.batchId || null;
    if (draft?.batchId) {
      apiFetch(`/uploads/${draft.batchId}`)
        .then((response) => {
          sessionIdRef.current = response.item.id;
          setSession(response.item);
        })
        .catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true);
      setNetworkMessage("Сеть вернулась. Пробую продолжить загрузку.");
      if (resumeOnReconnectRef.current && files.length && !busy) {
        startUploadRef.current?.({ silent: true }).catch(() => undefined);
      }
    }

    function handleOffline() {
      setIsOnline(false);
      setNetworkMessage("Интернет пропал. Загрузка поставлена на паузу и сможет продолжиться.");
    }

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [busy, files.length]);

  useEffect(() => {
    queueRef.current = queue;
  }, [queue]);

  useEffect(() => {
    return () => {
      if (draftSyncTimeoutRef.current) {
        window.clearTimeout(draftSyncTimeoutRef.current);
      }
    };
  }, []);

  function rememberSession(nextSession) {
    sessionIdRef.current = nextSession?.id || null;
    setSession(nextSession);
  }

  useEffect(() => {
    if (!startedAt || !totals.uploadedBytes || !totals.totalBytes) {
      setTelemetry({ speed: 0, eta: 0 });
      return;
    }
    const elapsed = Math.max((Date.now() - startedAt) / 1000, 1);
    const speed = totals.uploadedBytes / elapsed;
    const eta = speed ? (totals.totalBytes - totals.uploadedBytes) / speed : 0;
    setTelemetry({ speed, eta });
  }, [startedAt, totals.totalBytes, totals.uploadedBytes]);

  function persistDraftSnapshot(nextQueue) {
    if (!sessionIdRef.current) return;
    const draft = toDraft(sessionIdRef.current, nextQueue);
    writeDraft(draft);
    setResumeDraft(draft);
  }

  function scheduleDraftSync() {
    if (!sessionIdRef.current || draftSyncTimeoutRef.current) return;
    draftSyncTimeoutRef.current = window.setTimeout(() => {
      draftSyncTimeoutRef.current = null;
      persistDraftSnapshot(queueRef.current);
    }, DRAFT_SYNC_DELAY_MS);
  }

  function updateQueue(updater, { persist = "deferred" } = {}) {
    setQueue((current) => {
      const next = updater(current);
      queueRef.current = next;
      if (persist === "immediate") {
        if (draftSyncTimeoutRef.current) {
          window.clearTimeout(draftSyncTimeoutRef.current);
          draftSyncTimeoutRef.current = null;
        }
        persistDraftSnapshot(next);
      } else if (persist === "deferred") {
        scheduleDraftSync();
      }
      return next;
    });
  }

  function attachFiles(list) {
    const nextFiles = Array.from(list || []);
    const draft = readDraft();
    const matchingDraft = sameSignatureSet(nextFiles, draft) ? draft : null;
    const nextQueue = queueFromFiles(nextFiles, matchingDraft, preferredChunkSize);
    setFiles(nextFiles);
    queueRef.current = nextQueue;
    setQueue(nextQueue);
    setError("");
    setNetworkMessage(
      matchingDraft
        ? "Нашёл незавершённую загрузку. Можно продолжить без повторной отправки уже загруженных частей."
        : ""
    );
    if (matchingDraft?.batchId) {
      apiFetch(`/uploads/${matchingDraft.batchId}`)
        .then((response) => rememberSession(response.item))
        .catch(() => undefined);
    } else {
      rememberSession(null);
    }
  }

  async function ensureBatch() {
    const draft = readDraft();
    if (files.length && sameSignatureSet(files, draft) && draft?.batchId) {
      return draft.batchId;
    }
    const response = await apiFetch("/uploads", {
      method: "POST",
      body: {
        clientTotalFiles: files.length,
        totalBytes: files.reduce((sum, file) => sum + file.size, 0),
      },
    });
    rememberSession(response.item);
    const freshDraft = toDraft(response.item.id, queueRef.current);
    writeDraft(freshDraft);
    setResumeDraft(freshDraft);
    return response.item.id;
  }

  async function syncServerFile(batchId, entry) {
    const totalChunks = Math.ceil(entry.size / entry.chunkSize);
    const response = await apiFetch(`/uploads/${batchId}/files/sync`, {
      method: "POST",
      body: {
        clientFileId: entry.signature,
        originalFilename: entry.name,
        sizeBytes: entry.size,
        mimeType: entry.file.type || "application/octet-stream",
        chunkSize: entry.chunkSize,
        totalChunks,
      },
    });
    const item = response.item;
    updateQueue(
      (current) =>
        current.map((candidate) =>
          candidate.signature === entry.signature
            ? {
                ...candidate,
                fileId: item.id,
                uploadedBytes: item.uploadedBytes,
                progress: item.sizeBytes ? item.uploadedBytes / item.sizeBytes : 0,
                status: item.status === "uploaded" ? "uploaded" : candidate.status,
                error: "",
              }
            : candidate
        ),
      { persist: "immediate" }
    );
    if (response.batch) {
      rememberSession(response.batch);
    }
    return item;
  }

  async function uploadEntry(batchId, entry) {
    const synced = await syncServerFile(batchId, entry);
    let offset = synced.uploadedBytes || 0;
    if (offset >= entry.size) {
      updateQueue(
        (current) =>
          current.map((candidate) =>
            candidate.signature === entry.signature
              ? { ...candidate, fileId: synced.id, uploadedBytes: entry.size, progress: 1, status: "uploaded" }
              : candidate
          ),
        { persist: "immediate" }
      );
      return synced.id;
    }

    updateQueue(
      (current) =>
        current.map((candidate) =>
          candidate.signature === entry.signature
            ? { ...candidate, fileId: synced.id, status: "uploading", error: "" }
            : candidate
        ),
      { persist: "immediate" }
    );

    while (offset < entry.size) {
      if (!navigator.onLine) {
        const interruption = new Error("Internet connection lost");
        interruption.code = "NETWORK";
        throw interruption;
      }
      const end = Math.min(offset + entry.chunkSize, entry.size);
      const chunk = entry.file.slice(offset, end);
      try {
        const response = await uploadBinaryChunk(`/uploads/${batchId}/files/${synced.id}/chunk`, chunk, {
          token: getStoredToken(),
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Start-Byte": offset,
            "X-Chunk-Index": Math.floor(offset / entry.chunkSize),
          },
          onProgress: (loaded) => {
            const now = Date.now();
            if (loaded < chunk.size && now - lastProgressUpdateRef.current < PROGRESS_REFRESH_MS) {
              return;
            }
            lastProgressUpdateRef.current = now;
            updateQueue(
              (current) =>
                current.map((candidate) =>
                  candidate.signature === entry.signature
                    ? {
                        ...candidate,
                        uploadedBytes: Math.min(offset + loaded, entry.size),
                        progress: Math.min((offset + loaded) / entry.size, 1),
                        status: "uploading",
                      }
                    : candidate
                ),
              { persist: "none" }
            );
          },
        });
        offset = response.item.uploadedBytes;
        if (response.batch) {
          rememberSession(response.batch);
        }
        updateQueue(
          (current) =>
            current.map((candidate) =>
              candidate.signature === entry.signature
                ? {
                    ...candidate,
                    fileId: response.item.id,
                    uploadedBytes: response.item.uploadedBytes,
                    progress: entry.size ? response.item.uploadedBytes / entry.size : 1,
                    status: response.item.status === "uploaded" ? "uploaded" : "uploading",
                    error: "",
                  }
                : candidate
            ),
          { persist: "immediate" }
        );
      } catch (chunkError) {
        if (chunkError.status === 409 && chunkError.payload?.expectedStartByte !== undefined) {
          offset = chunkError.payload.expectedStartByte;
          continue;
        }
        chunkError.code = chunkError.code || (navigator.onLine ? "UPLOAD" : "NETWORK");
        throw chunkError;
      }
    }

    await apiFetch(`/uploads/${batchId}/files/${synced.id}/finalize`, { method: "POST" });
    updateQueue(
      (current) =>
        current.map((candidate) =>
          candidate.signature === entry.signature
            ? { ...candidate, uploadedBytes: entry.size, progress: 1, status: "uploaded", error: "" }
            : candidate
        ),
      { persist: "immediate" }
    );
    return synced.id;
  }

  async function watchBatch(batchId) {
    const poll = window.setInterval(async () => {
      try {
        const response = await apiFetch(`/uploads/${batchId}`);
        rememberSession(response.item);
        if (["completed", "completed_with_warnings", "failed"].includes(response.item.status)) {
          window.clearInterval(poll);
        }
      } catch {
        window.clearInterval(poll);
      }
    }, 1500);
  }

  async function startUpload({ silent = false } = {}) {
    if (!files.length || busy) return;
    setBusy(true);
    if (!silent) {
      setError("");
    }
    if (!startedAt) {
      setStartedAt(Date.now());
    }

    try {
      const batchId = await ensureBatch();
      if (!session || session.id !== batchId) {
        const loadedBatch = await apiFetch(`/uploads/${batchId}`);
        rememberSession(loadedBatch.item);
      }

      lastProgressUpdateRef.current = 0;
      const entries =
        queueRef.current.length ? queueRef.current : queueFromFiles(files, readDraft(), preferredChunkSize);
      for (const entry of entries) {
        await uploadEntry(batchId, entry);
      }

      resumeOnReconnectRef.current = false;
      setNetworkMessage("Все части загружены. Передаю батч в обработку.");
      const commit = await apiFetch(`/uploads/${batchId}/commit`, { method: "POST" });
      rememberSession(commit.item);
      writeDraft(null);
      setResumeDraft(null);
      sessionIdRef.current = null;
      await watchBatch(batchId);
    } catch (submitError) {
      const isNetworkIssue =
        submitError.code === "NETWORK" ||
        /network/i.test(submitError.message) ||
        !navigator.onLine;
      resumeOnReconnectRef.current = isNetworkIssue;
      updateQueue(
        (current) =>
          current.map((entry) =>
            entry.status === "uploading"
              ? {
                  ...entry,
                  status: isNetworkIssue ? "paused" : "failed",
                  error: submitError.message,
                }
              : entry
          ),
        { persist: "immediate" }
      );
      setError(
        isNetworkIssue
          ? "Соединение оборвалось. Уже загруженные части сохранены, можно продолжить."
          : submitError.message
      );
      setNetworkMessage(
        isNetworkIssue
          ? "Обнаружен сетевой обрыв. Продолжение возможно автоматически после возврата сети или кнопкой ниже."
          : ""
      );
    } finally {
      setBusy(false);
    }
  }

  function resetDraft() {
    const nextQueue = queueFromFiles(files, null, preferredChunkSize);
    writeDraft(null);
    setResumeDraft(null);
    rememberSession(null);
    queueRef.current = nextQueue;
    setQueue(nextQueue);
    setNetworkMessage("");
    setError("");
    resumeOnReconnectRef.current = false;
  }

  const resumePossible = queue.some((entry) => entry.status === "paused" || entry.uploadedBytes > 0);
  startUploadRef.current = startUpload;

  return (
    <div className="page-grid upload-layout">
      <section className="glass panel upload-hero">
        <div className="section-head">
          <div>
            <p className="eyebrow">resumable uploader</p>
            <h1>Массовая загрузка с продолжением после обрыва</h1>
            <p className="muted">
              Архивы и медиа отправляются по частям. Если интернет прервётся, уже залитые куски не теряются.
            </p>
          </div>
          <div className={`status-pill ${isOnline ? "" : "warning-pill"}`}>
            {isOnline ? "онлайн" : "оффлайн"}
          </div>
        </div>

        <div
          className="dropzone upload-dropzone"
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
          <div className="upload-dropzone-copy">
            <h3>Перетащите файлы, архивы или целые пачки</h3>
            <p className="muted">
              После сбоя можно повторно выбрать те же файлы и продолжить с того места, где остановилось.
            </p>
          </div>
          <div className="button-row">
            <button type="button" className="primary-button" onClick={() => inputRef.current?.click()}>
              Выбрать файлы
            </button>
            <button type="button" className="ghost-button" disabled={!files.length || busy} onClick={() => startUpload()}>
              {busy ? "Заливаю…" : resumePossible ? "Продолжить загрузку" : "Начать импорт"}
            </button>
            <button type="button" className="ghost-button" disabled={!resumeDraft} onClick={resetDraft}>
              Сбросить прогресс
            </button>
          </div>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <span>Файлов</span>
            <strong>{totals.totalFiles}</strong>
          </div>
          <div className="stat-card">
            <span>Загружено</span>
            <strong>
              {formatBytes(totals.uploadedBytes)} / {formatBytes(totals.totalBytes)}
            </strong>
          </div>
          <div className="stat-card">
            <span>Скорость</span>
            <strong>{telemetry.speed ? formatRate(telemetry.speed) : "—"}</strong>
          </div>
          <div className="stat-card">
            <span>Осталось</span>
            <strong>{telemetry.eta ? formatDuration(telemetry.eta) : "—"}</strong>
          </div>
        </div>

        <div className="upload-status-row">
          {session ? (
            <div className="panel-block">
              <h3>Серверная сессия</h3>
              <p className="muted">Batch: {session.id}</p>
              <p>
                Статус: <strong>{session.status}</strong>
              </p>
              <p>
                Обработано: {session.processedItems}/{session.totalItems || "?"}
              </p>
            </div>
          ) : (
            <div className="panel-block">
              <h3>Сессия ещё не создана</h3>
              <p className="muted">Выберите файлы и начните импорт.</p>
            </div>
          )}
          <div className="panel-block">
            <h3>Восстановление</h3>
            <p className="muted">
              {resumeDraft
                ? "Черновик загрузки найден и сохранён в браузере."
                : "Черновика загрузки пока нет."}
            </p>
            <p className="muted">
              При обновлении страницы просто снова выберите тот же набор файлов.
            </p>
          </div>
        </div>

        {networkMessage ? <div className="success-box">{networkMessage}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}
      </section>

      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">queue</p>
            <h2>Очередь по файлам</h2>
          </div>
        </div>
        <div className="list-stack">
          {queue.map((entry) => (
            <div key={entry.signature} className="queue-row queue-row-vertical">
              <div className="queue-copy">
                <strong>{entry.name}</strong>
                <p className="muted">
                  {formatBytes(entry.size)} • {entry.status}
                </p>
                {entry.error ? <p className="muted">{entry.error}</p> : null}
              </div>
              <div className="queue-progress queue-progress-wide">
                <div className="metric-bar-head">
                  <span>
                    {formatBytes(entry.uploadedBytes)} / {formatBytes(entry.size)}
                  </span>
                  <span>{Math.round((entry.progress || 0) * 100)}%</span>
                </div>
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
