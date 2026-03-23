import { useEffect, useMemo, useRef, useState } from "react";

import { apiFetch, getStoredToken, uploadBinaryChunk } from "../api";
import { formatBytes, formatDuration, formatRate } from "../lib/format";

const DRAFT_KEY = "mediahub_upload_draft_v2";
const DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024;
const DRAFT_SYNC_DELAY_MS = 800;
const PROGRESS_REFRESH_MS = 120;
const SPEED_WINDOW_MS = 6000;
const MAX_PARALLEL_CHUNKS = 4;

function pickChunkSize(fileSize, preferredChunkSize) {
  const base = Math.max(preferredChunkSize || DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_SIZE);
  if (fileSize >= 1024 * 1024 * 1024) {
    return Math.max(base, 16 * 1024 * 1024);
  }
  if (fileSize >= 256 * 1024 * 1024) {
    return Math.max(base, 12 * 1024 * 1024);
  }
  return base;
}

function deriveCompletedChunks(uploadedBytes, size, chunkSize) {
  if (!uploadedBytes || !size || !chunkSize) {
    return [];
  }
  const cappedBytes = Math.min(uploadedBytes, size);
  const fullChunks = Math.floor(cappedBytes / chunkSize);
  const chunks = Array.from({ length: fullChunks }, (_, index) => index);
  const hasPartialChunk = cappedBytes % chunkSize !== 0 && cappedBytes < size;
  if (hasPartialChunk) {
    chunks.push(fullChunks);
  }
  if (cappedBytes >= size) {
    const totalChunks = Math.ceil(size / chunkSize);
    return Array.from({ length: totalChunks }, (_, index) => index);
  }
  return chunks;
}

function mergeCompletedChunks(...sources) {
  const merged = new Set();
  sources.flat().forEach((value) => {
    if (Number.isInteger(value) && value >= 0) {
      merged.add(value);
    }
  });
  return [...merged].sort((left, right) => left - right);
}

function completedBytesFromChunks(completedChunks, size, chunkSize) {
  if (!size || !chunkSize) {
    return 0;
  }
  const totalChunks = Math.ceil(size / chunkSize);
  return completedChunks.reduce((sum, chunkIndex) => {
    if (chunkIndex < 0 || chunkIndex >= totalChunks) {
      return sum;
    }
    const start = chunkIndex * chunkSize;
    const end = Math.min(start + chunkSize, size);
    return sum + Math.max(end - start, 0);
  }, 0);
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
    const chunkSize = saved?.chunkSize || pickChunkSize(file.size, preferredChunkSize);
    const completedChunks = mergeCompletedChunks(
      saved?.completedChunks || [],
      deriveCompletedChunks(saved?.uploadedBytes || 0, file.size, chunkSize)
    );
    const uploadedBytes = Math.min(
      Math.max(saved?.uploadedBytes || 0, completedBytesFromChunks(completedChunks, file.size, chunkSize)),
      file.size
    );
    return {
      signature,
      file,
      name: file.name,
      size: file.size,
      fileId: saved?.fileId || null,
      uploadedBytes,
      progress: file.size ? uploadedBytes / file.size : 0,
      status: saved ? saved.status || "paused" : "queued",
      chunkSize,
      completedChunks,
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
          completedChunks: entry.completedChunks || [],
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
  const speedSamplesRef = useRef([]);
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
    if (!startedAt || !totals.totalBytes) {
      speedSamplesRef.current = [];
      setTelemetry({ speed: 0, eta: 0 });
      return;
    }
    const now = Date.now();
    const nextSamples = [
      ...speedSamplesRef.current.filter((sample) => now - sample.timestamp <= SPEED_WINDOW_MS),
      { timestamp: now, uploadedBytes: totals.uploadedBytes },
    ];
    speedSamplesRef.current = nextSamples;
    let speed = 0;
    if (nextSamples.length >= 2) {
      const first = nextSamples[0];
      const last = nextSamples[nextSamples.length - 1];
      const elapsedSeconds = Math.max((last.timestamp - first.timestamp) / 1000, 0.25);
      speed = Math.max(0, (last.uploadedBytes - first.uploadedBytes) / elapsedSeconds);
    } else if (totals.uploadedBytes > 0) {
      const elapsed = Math.max((now - startedAt) / 1000, 1);
      speed = totals.uploadedBytes / elapsed;
    }
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
    const completedChunks = mergeCompletedChunks(
      entry.completedChunks || [],
      item.receivedChunkIndexes || [],
      deriveCompletedChunks(item.uploadedBytes || 0, entry.size, entry.chunkSize)
    );
    const uploadedBytes = Math.min(
      Math.max(item.uploadedBytes || 0, completedBytesFromChunks(completedChunks, entry.size, entry.chunkSize)),
      entry.size
    );
    updateQueue(
      (current) =>
        current.map((candidate) =>
          candidate.signature === entry.signature
            ? {
                ...candidate,
                fileId: item.id,
                uploadedBytes,
                progress: entry.size ? uploadedBytes / entry.size : 0,
                completedChunks,
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
    const totalChunks = Math.ceil(entry.size / entry.chunkSize);
    let completedChunks = mergeCompletedChunks(
      entry.completedChunks || [],
      synced.receivedChunkIndexes || [],
      deriveCompletedChunks(synced.uploadedBytes || 0, entry.size, entry.chunkSize)
    );
    if (completedBytesFromChunks(completedChunks, entry.size, entry.chunkSize) >= entry.size) {
      updateQueue(
        (current) =>
          current.map((candidate) =>
            candidate.signature === entry.signature
              ? {
                  ...candidate,
                  fileId: synced.id,
                  uploadedBytes: entry.size,
                  progress: 1,
                  completedChunks,
                  status: "uploaded",
                }
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

    const completedSet = new Set(completedChunks);
    const inFlightProgress = new Map();
    const pendingChunkIndexes = Array.from({ length: totalChunks }, (_, index) => index).filter(
      (index) => !completedSet.has(index)
    );
    let nextChunkCursor = 0;

    function refreshEntryProgress({ persist = "none", status = "uploading" } = {}) {
      const committedBytes = completedBytesFromChunks([...completedSet], entry.size, entry.chunkSize);
      const inflightBytes = [...inFlightProgress.values()].reduce((sum, value) => sum + value, 0);
      const uploadedBytes = Math.min(committedBytes + inflightBytes, entry.size);
      const mergedCompletedChunks = [...completedSet].sort((left, right) => left - right);
      updateQueue(
        (current) =>
          current.map((candidate) =>
            candidate.signature === entry.signature
              ? {
                  ...candidate,
                  fileId: synced.id,
                  uploadedBytes: Math.max(candidate.uploadedBytes || 0, uploadedBytes),
                  progress: entry.size ? Math.min(uploadedBytes / entry.size, 1) : 1,
                  completedChunks: mergedCompletedChunks,
                  status,
                  error: "",
                }
              : candidate
          ),
        { persist }
      );
    }

    async function uploadChunkByIndex(chunkIndex) {
      if (!navigator.onLine) {
        const interruption = new Error("Internet connection lost");
        interruption.code = "NETWORK";
        throw interruption;
      }

      const startByte = chunkIndex * entry.chunkSize;
      const endByte = Math.min(startByte + entry.chunkSize, entry.size);
      const chunk = entry.file.slice(startByte, endByte);
      inFlightProgress.set(chunkIndex, 0);
      refreshEntryProgress();

      try {
        const response = await uploadBinaryChunk(`/uploads/${batchId}/files/${synced.id}/chunk`, chunk, {
          token: getStoredToken(),
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Start-Byte": startByte,
            "X-Chunk-Index": chunkIndex,
          },
          onProgress: (loaded) => {
            const now = Date.now();
            if (loaded < chunk.size && now - lastProgressUpdateRef.current < PROGRESS_REFRESH_MS) {
              return;
            }
            lastProgressUpdateRef.current = now;
            inFlightProgress.set(chunkIndex, loaded);
            refreshEntryProgress();
          },
        });
        inFlightProgress.delete(chunkIndex);
        mergeCompletedChunks([chunkIndex], [...completedSet], response.item.receivedChunkIndexes || []).forEach(
          (value) => completedSet.add(value)
        );
        if (response.batch) {
          rememberSession(response.batch);
        }
        refreshEntryProgress({
          persist: "immediate",
          status: response.item.status === "uploaded" ? "uploaded" : "uploading",
        });
      } catch (chunkError) {
        inFlightProgress.delete(chunkIndex);
        if (chunkError.status === 409 && chunkError.payload?.expectedStartByte !== undefined) {
          mergeCompletedChunks(
            [...completedSet],
            chunkError.payload?.item?.receivedChunkIndexes || []
          ).forEach((value) => completedSet.add(value));
          refreshEntryProgress({ persist: "immediate" });
          return;
        }
        chunkError.code = chunkError.code || (navigator.onLine ? "UPLOAD" : "NETWORK");
        throw chunkError;
      }
    }

    const workerCount = Math.min(MAX_PARALLEL_CHUNKS, pendingChunkIndexes.length || 1);
    await Promise.all(
      Array.from({ length: workerCount }, async () => {
        while (nextChunkCursor < pendingChunkIndexes.length) {
          const chunkIndex = pendingChunkIndexes[nextChunkCursor];
          nextChunkCursor += 1;
          await uploadChunkByIndex(chunkIndex);
        }
      })
    );

    await apiFetch(`/uploads/${batchId}/files/${synced.id}/finalize`, { method: "POST" });
    updateQueue(
      (current) =>
        current.map((candidate) =>
          candidate.signature === entry.signature
            ? {
                ...candidate,
                uploadedBytes: entry.size,
                progress: 1,
                completedChunks: Array.from({ length: totalChunks }, (_, index) => index),
                status: "uploaded",
                error: "",
              }
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
      speedSamplesRef.current = [];
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
    speedSamplesRef.current = [];
    setTelemetry({ speed: 0, eta: 0 });
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
