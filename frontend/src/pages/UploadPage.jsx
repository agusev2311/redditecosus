import { useEffect, useMemo, useRef, useState } from "react";

import { apiFetch, getStoredToken, uploadBinaryChunk } from "../api";
import { formatBytes, formatDuration, formatMegabitsPerSecond, formatRate } from "../lib/format";

const DRAFT_KEY = "mediahub_upload_draft_v3";
const DEFAULT_CHUNK_SIZE = 16 * 1024 * 1024;
const DRAFT_SYNC_DELAY_MS = 1400;
const PROGRESS_REFRESH_MS = 140;
const SPEED_WINDOW_MS = 5000;
const MAX_PARALLEL_FILES = 2;
const MAX_PARALLEL_PARTS = 4;

function pickChunkSize(fileSize, preferredChunkSize) {
  const base = Math.max(preferredChunkSize || DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_SIZE);
  if (fileSize >= 2 * 1024 * 1024 * 1024) {
    return Math.max(base, 32 * 1024 * 1024);
  }
  if (fileSize >= 512 * 1024 * 1024) {
    return Math.max(base, 24 * 1024 * 1024);
  }
  if (fileSize >= 64 * 1024 * 1024) {
    return Math.max(base, 16 * 1024 * 1024);
  }
  return base;
}

function pickPartWorkers(fileSize, totalFiles) {
  if (totalFiles <= 1) {
    return fileSize >= 256 * 1024 * 1024 ? MAX_PARALLEL_PARTS : 3;
  }
  if (fileSize >= 512 * 1024 * 1024) {
    return 2;
  }
  return 1;
}

function deriveCompletedChunks(uploadedBytes, size, chunkSize) {
  if (!uploadedBytes || !size || !chunkSize) {
    return [];
  }
  const cappedBytes = Math.min(uploadedBytes, size);
  const totalChunks = Math.ceil(size / chunkSize);
  if (cappedBytes >= size) {
    return Array.from({ length: totalChunks }, (_, index) => index);
  }
  const chunks = [];
  const fullChunks = Math.floor(cappedBytes / chunkSize);
  for (let index = 0; index < fullChunks; index += 1) {
    chunks.push(index);
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
    const totalChunks = Math.ceil(file.size / chunkSize);
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
      totalChunks,
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
          totalChunks: entry.totalChunks,
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
      setNetworkMessage("Сеть вернулась. Новый upload engine пробует продолжить загрузку.");
      if (resumeOnReconnectRef.current && files.length && !busy) {
        startUploadRef.current?.({ silent: true }).catch(() => undefined);
      }
    }

    function handleOffline() {
      setIsOnline(false);
      setNetworkMessage("Интернет пропал. Уже загруженные части сохранены, продолжение будет с них.");
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
      const elapsedSeconds = Math.max((last.timestamp - first.timestamp) / 1000, 0.2);
      speed = Math.max(0, (last.uploadedBytes - first.uploadedBytes) / elapsedSeconds);
    } else if (totals.uploadedBytes > 0) {
      const elapsed = Math.max((now - startedAt) / 1000, 1);
      speed = totals.uploadedBytes / elapsed;
    }
    const eta = speed ? (totals.totalBytes - totals.uploadedBytes) / speed : 0;
    setTelemetry({ speed, eta });
  }, [startedAt, totals.totalBytes, totals.uploadedBytes]);

  function rememberSession(nextSession) {
    sessionIdRef.current = nextSession?.id || null;
    setSession(nextSession);
  }

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

  function getQueueEntry(signature) {
    return queueRef.current.find((entry) => entry.signature === signature) || null;
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
        ? "Нашёл незавершённую загрузку. Продолжаю по серверному состоянию без повторной отправки готовых частей."
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

  async function openRemoteFile(batchId, signature) {
    const entry = getQueueEntry(signature);
    if (!entry) {
      throw new Error("Upload entry disappeared");
    }
    const response = await apiFetch(`/uploads/${batchId}/files/sync`, {
      method: "POST",
      body: {
        clientFileId: entry.signature,
        originalFilename: entry.name,
        sizeBytes: entry.size,
        mimeType: entry.file.type || "application/octet-stream",
        chunkSize: entry.chunkSize,
        totalChunks: entry.totalChunks,
      },
    });
    const serverEntry = response.item;
    const effectiveChunkSize = Math.max(serverEntry.chunkSize || entry.chunkSize || DEFAULT_CHUNK_SIZE, 1);
    const effectiveTotalChunks = Math.max(
      serverEntry.totalChunks || Math.ceil(entry.size / effectiveChunkSize) || 1,
      1
    );
    const completedChunks = mergeCompletedChunks(
      serverEntry.receivedChunkIndexes || [],
      deriveCompletedChunks(serverEntry.uploadedBytes || 0, entry.size, effectiveChunkSize)
    );
    const uploadedBytes = Math.min(
      Math.max(
        serverEntry.uploadedBytes || 0,
        completedBytesFromChunks(completedChunks, entry.size, effectiveChunkSize)
      ),
      entry.size
    );
    updateQueue(
      (current) =>
        current.map((candidate) =>
          candidate.signature === signature
            ? {
                ...candidate,
                fileId: serverEntry.id,
                uploadedBytes,
                progress: entry.size ? uploadedBytes / entry.size : 0,
                chunkSize: effectiveChunkSize,
                totalChunks: effectiveTotalChunks,
                completedChunks,
                status: uploadedBytes >= entry.size ? "uploaded" : "uploading",
                error: "",
              }
            : candidate
        ),
      { persist: "immediate" }
    );
    if (response.batch) {
      rememberSession(response.batch);
    }
    return {
      fileId: serverEntry.id,
      chunkSize: effectiveChunkSize,
      completedChunks,
      uploadedBytes,
      totalChunks: effectiveTotalChunks,
    };
  }

  async function syncQueueEntries(batchId) {
    const signatures = (queueRef.current || []).map((entry) => entry.signature);
    if (!signatures.length) {
      return;
    }

    let cursor = 0;
    let syncError = null;
    const workers = Math.min(MAX_PARALLEL_FILES, signatures.length || 1);

    await Promise.all(
      Array.from({ length: workers }, async () => {
        while (!syncError && cursor < signatures.length) {
          const signature = signatures[cursor];
          cursor += 1;
          try {
            await openRemoteFile(batchId, signature);
          } catch (errorObject) {
            syncError = errorObject;
          }
        }
      })
    );

    if (syncError) {
      throw syncError;
    }
  }

  async function finalizeRemoteFile(batchId, signature) {
    const entry = getQueueEntry(signature);
    if (!entry?.fileId) return;
    await apiFetch(`/uploads/${batchId}/files/${entry.fileId}/finalize`, { method: "POST" });
    updateQueue(
      (current) =>
        current.map((candidate) =>
          candidate.signature === signature
            ? {
                ...candidate,
                uploadedBytes: candidate.size,
                progress: 1,
                completedChunks: Array.from({ length: candidate.totalChunks }, (_, index) => index),
                status: "uploaded",
                error: "",
              }
            : candidate
        ),
      { persist: "immediate" }
    );
  }

  async function uploadEntryAttempt(batchId, signature) {
    const synced = await openRemoteFile(batchId, signature);
    const entry = getQueueEntry(signature);
    if (!entry) {
      throw new Error("Upload entry disappeared");
    }

    const completedSet = new Set(synced.completedChunks);
    const inFlightProgress = new Map();
    const pendingIndexes = Array.from({ length: entry.totalChunks }, (_, index) => index).filter(
      (index) => !completedSet.has(index)
    );

    if (!pendingIndexes.length) {
      await finalizeRemoteFile(batchId, signature);
      return;
    }

    const partWorkers = Math.min(
      pickPartWorkers(entry.size, queueRef.current.length),
      pendingIndexes.length || 1
    );
    let cursor = 0;
    let fatalError = null;

    function refreshProgress({ persist = "none", status = "uploading" } = {}) {
      const latest = getQueueEntry(signature);
      if (!latest) return;
      const committedBytes = completedBytesFromChunks([...completedSet], latest.size, latest.chunkSize);
      const inflightBytes = [...inFlightProgress.values()].reduce((sum, value) => sum + value, 0);
      const uploadedBytes = Math.min(committedBytes + inflightBytes, latest.size);
      updateQueue(
        (current) =>
          current.map((candidate) =>
            candidate.signature === signature
              ? {
                  ...candidate,
                  uploadedBytes: Math.max(candidate.uploadedBytes || 0, uploadedBytes),
                  progress: latest.size ? Math.min(uploadedBytes / latest.size, 1) : 1,
                  completedChunks: [...completedSet].sort((left, right) => left - right),
                  status,
                  error: "",
                }
              : candidate
          ),
        { persist }
      );
    }

    async function sendChunk(chunkIndex) {
      if (!navigator.onLine) {
        const interruption = new Error("Internet connection lost");
        interruption.code = "NETWORK";
        throw interruption;
      }
      const latest = getQueueEntry(signature);
      if (!latest) {
        throw new Error("Upload entry disappeared");
      }
      const startByte = chunkIndex * latest.chunkSize;
      const endByte = Math.min(startByte + latest.chunkSize, latest.size);
      const chunk = latest.file.slice(startByte, endByte);
      inFlightProgress.set(chunkIndex, 0);
      refreshProgress();

      try {
        const response = await uploadBinaryChunk(`/uploads/${batchId}/files/${latest.fileId}/chunk`, chunk, {
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
            refreshProgress();
          },
        });
        inFlightProgress.delete(chunkIndex);
        completedSet.add(chunkIndex);
        refreshProgress({
          persist: completedSet.size % 2 === 0 ? "immediate" : "deferred",
          status: response.item?.status === "uploaded" ? "uploaded" : "uploading",
        });
      } catch (chunkError) {
        inFlightProgress.delete(chunkIndex);
        if (chunkError.status === 409) {
          chunkError.code = "RESYNC";
        } else if (!navigator.onLine || /network/i.test(chunkError.message)) {
          chunkError.code = "NETWORK";
        } else {
          chunkError.code = chunkError.code || "UPLOAD";
        }
        throw chunkError;
      }
    }

    await Promise.all(
      Array.from({ length: partWorkers }, async () => {
        while (!fatalError && cursor < pendingIndexes.length) {
          const chunkIndex = pendingIndexes[cursor];
          cursor += 1;
          try {
            await sendChunk(chunkIndex);
          } catch (err) {
            fatalError = err;
          }
        }
      })
    );

    if (fatalError) {
      throw fatalError;
    }

    await finalizeRemoteFile(batchId, signature);
  }

  async function uploadEntry(batchId, signature, attempt = 0) {
    try {
      await uploadEntryAttempt(batchId, signature);
    } catch (errorObject) {
      if (errorObject.code === "RESYNC" && attempt < 2) {
        return uploadEntry(batchId, signature, attempt + 1);
      }
      throw errorObject;
    }
  }

  async function uploadPendingEntries(batchId, signatures) {
    let cursor = 0;
    const fileWorkers = Math.min(MAX_PARALLEL_FILES, signatures.length || 1);
    await Promise.all(
      Array.from({ length: fileWorkers }, async () => {
        while (cursor < signatures.length) {
          const signature = signatures[cursor];
          cursor += 1;
          await uploadEntry(batchId, signature);
        }
      })
    );
  }

  async function watchBatch(batchId) {
    const poll = window.setInterval(async () => {
      try {
        const response = await apiFetch(`/uploads/${batchId}`);
        rememberSession(response.item);
        if (["completed", "completed_with_warnings", "failed"].includes(response.item.status)) {
          if (response.item.status === "completed_with_warnings" && response.item.errorMessage) {
            setError(response.item.errorMessage);
          }
          if (response.item.status === "failed" && response.item.errorMessage) {
            setError(response.item.errorMessage);
          }
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
      updateQueue(
        (current) =>
          current.map((entry) => ({
            ...entry,
            status: entry.uploadedBytes >= entry.size ? entry.status : "uploading",
            error: "",
          })),
        { persist: "deferred" }
      );
      await syncQueueEntries(batchId);
      const pendingSignatures = queueRef.current
        .filter((entry) => {
          const completedChunkCount = entry.completedChunks?.length || 0;
          return entry.uploadedBytes < entry.size || completedChunkCount < entry.totalChunks;
        })
        .map((entry) => entry.signature);

      await uploadPendingEntries(batchId, pendingSignatures);

      resumeOnReconnectRef.current = false;
      setNetworkMessage("Все данные загружены новым upload engine. Передаю батч в обработку.");
      let commit;
      try {
        commit = await apiFetch(`/uploads/${batchId}/commit`, { method: "POST" });
      } catch (commitError) {
        if (!/not fully uploaded/i.test(commitError.message || "")) {
          throw commitError;
        }
        await syncQueueEntries(batchId);
        const repairSignatures = queueRef.current
          .filter((entry) => {
            const completedChunkCount = entry.completedChunks?.length || 0;
            return entry.uploadedBytes < entry.size || completedChunkCount < entry.totalChunks;
          })
          .map((entry) => entry.signature);
        if (repairSignatures.length) {
          setNetworkMessage("Сервер нашёл недостающие части. Догружаю только пропущенные куски и повторяю commit.");
          await uploadPendingEntries(batchId, repairSignatures);
        }
        commit = await apiFetch(`/uploads/${batchId}/commit`, { method: "POST" });
      }
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
          ? "Соединение оборвалось. Уже переданные части сохранены, загрузку можно продолжить."
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
            <p className="eyebrow">upload engine v2</p>
            <h1>Массовая загрузка с быстрым resume</h1>
            <p className="muted">
              Переписанный движок грузит крупнее, реже пишет метаданные и продолжает с серверного состояния после обрыва.
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
              Большие файлы режутся на более крупные части, а батч может грузить несколько файлов параллельно.
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
            <small className="muted stat-subcopy">
              {telemetry.speed ? formatMegabitsPerSecond(telemetry.speed) : "как в speedtest"}
            </small>
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
              <p>
                Сохранено: {session.storedItems || 0} • дублей: {session.duplicateItems || 0} • ошибок: {session.failedItems || 0}
              </p>
              {session.errorMessage ? <p className="muted">Причина: {session.errorMessage}</p> : null}
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
              При обновлении страницы снова выберите тот же набор файлов, и клиент сверится с сервером.
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
                  {formatBytes(entry.size)} • {entry.status} • chunk {formatBytes(entry.chunkSize)}
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
