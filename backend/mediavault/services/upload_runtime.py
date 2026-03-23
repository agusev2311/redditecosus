from __future__ import annotations

import json
import threading
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from ..models import UploadBatch, UploadFile
from ..utils import ensure_parent
from .storage import collect_upload_chunk_state, upload_marker_dir

_LOCKS_GUARD = threading.Lock()
_UPLOAD_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(upload: UploadFile) -> threading.Lock:
    key = upload.id or upload.temp_path
    with _LOCKS_GUARD:
        if key not in _UPLOAD_LOCKS:
            _UPLOAD_LOCKS[key] = threading.Lock()
        return _UPLOAD_LOCKS[key]


def _meta_path(upload: UploadFile) -> Path:
    temp_path = Path(upload.temp_path)
    return temp_path.with_name(f"{temp_path.name}.upload.json")


def _bitmap_path(upload: UploadFile) -> Path:
    temp_path = Path(upload.temp_path)
    return temp_path.with_name(f"{temp_path.name}.bitmap")


def _default_chunk_size(upload: UploadFile) -> int:
    return max(int(upload.chunk_size or 0), max(int(upload.size_bytes or 0), 1))


def _default_total_chunks(upload: UploadFile) -> int:
    return max(int(upload.total_chunks or 0), 1)


def _default_state(upload: UploadFile) -> dict:
    return {
        "sizeBytes": int(upload.size_bytes or 0),
        "chunkSize": _default_chunk_size(upload),
        "totalChunks": _default_total_chunks(upload),
        "uploadedBytes": int(upload.uploaded_bytes or 0),
        "uploadedChunks": int(upload.uploaded_chunks or 0),
        "updatedAt": datetime.utcnow().isoformat() + "Z",
    }


def _write_state(meta_path: Path, state: dict) -> None:
    ensure_parent(meta_path)
    temp_path = meta_path.with_suffix(f"{meta_path.suffix}.tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(meta_path)


def _read_state(meta_path: Path) -> dict | None:
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_received_indexes(bitmap_path: Path, total_chunks: int) -> list[int]:
    if not bitmap_path.exists():
        return []
    with bitmap_path.open("rb") as handle:
        bitmap = handle.read()
    return [
        index
        for index, value in enumerate(bitmap[:total_chunks])
        if value == 1
    ]


def _migrate_legacy_markers(upload: UploadFile, state: dict, bitmap_path: Path) -> tuple[list[int], int]:
    received_indexes, uploaded_bytes = collect_upload_chunk_state(
        Path(upload.temp_path),
        state["chunkSize"],
        state["totalChunks"],
        state["sizeBytes"],
    )
    ensure_parent(bitmap_path)
    bitmap = bytearray(state["totalChunks"])
    for index in received_indexes:
        if 0 <= index < len(bitmap):
            bitmap[index] = 1
    bitmap_path.write_bytes(bytes(bitmap))
    state["uploadedChunks"] = len(received_indexes)
    state["uploadedBytes"] = uploaded_bytes
    legacy_dir = upload_marker_dir(Path(upload.temp_path))
    if legacy_dir.exists():
        with suppress(OSError):
            for marker in legacy_dir.iterdir():
                marker.unlink(missing_ok=True)
            legacy_dir.rmdir()
    return received_indexes, uploaded_bytes


def ensure_runtime(upload: UploadFile) -> dict:
    meta_path = _meta_path(upload)
    bitmap_path = _bitmap_path(upload)
    state = _read_state(meta_path) or _default_state(upload)
    state["sizeBytes"] = int(upload.size_bytes or state["sizeBytes"] or 0)
    state["chunkSize"] = max(int(upload.chunk_size or state["chunkSize"] or 0), 1)
    state["totalChunks"] = max(int(upload.total_chunks or state["totalChunks"] or 0), 1)
    state["uploadedBytes"] = min(int(state.get("uploadedBytes") or 0), state["sizeBytes"] or int(state.get("uploadedBytes") or 0))
    state["uploadedChunks"] = min(int(state.get("uploadedChunks") or 0), state["totalChunks"])

    bitmap_exists = bitmap_path.exists()
    if not bitmap_exists:
        if upload.total_chunks and upload.total_chunks > 1:
            _migrate_legacy_markers(upload, state, bitmap_path)
        else:
            ensure_parent(bitmap_path)
            bitmap_path.write_bytes(bytes(state["totalChunks"]))
    else:
        current_size = bitmap_path.stat().st_size
        if current_size < state["totalChunks"]:
            with bitmap_path.open("ab") as handle:
                handle.write(bytes(state["totalChunks"] - current_size))
        elif current_size > state["totalChunks"]:
            with bitmap_path.open("r+b") as handle:
                handle.truncate(state["totalChunks"])

    current_indexes = _read_received_indexes(bitmap_path, state["totalChunks"])
    state["uploadedChunks"] = len(current_indexes)
    if state["chunkSize"] > 0 and state["sizeBytes"] > 0:
        state["uploadedBytes"] = sum(
            min(((index + 1) * state["chunkSize"]), state["sizeBytes"]) - (index * state["chunkSize"])
            for index in current_indexes
        )
    state["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    _write_state(meta_path, state)
    return state


def get_runtime_state(upload: UploadFile, include_received_chunks: bool = False) -> dict:
    with _lock_for(upload):
        state = ensure_runtime(upload)
        if include_received_chunks:
            state["receivedChunkIndexes"] = _read_received_indexes(_bitmap_path(upload), state["totalChunks"])
        return state


def sync_upload_model(upload: UploadFile, state: dict) -> None:
    upload.size_bytes = int(state["sizeBytes"])
    upload.chunk_size = int(state["chunkSize"])
    upload.total_chunks = int(state["totalChunks"])
    upload.uploaded_bytes = int(state["uploadedBytes"])
    upload.uploaded_chunks = int(state["uploadedChunks"])
    is_fully_uploaded = upload.uploaded_bytes >= upload.size_bytes
    if upload.status not in {"processing", "completed", "failed"}:
        upload.status = "uploaded" if is_fully_uploaded else "uploading"
    if is_fully_uploaded and not upload.finalized_at:
        upload.finalized_at = datetime.utcnow()


def sync_batch_model(batch: UploadBatch, uploads: list[UploadFile]) -> None:
    batch.uploaded_bytes = 0
    batch.uploaded_files = 0
    if batch.status not in {"uploading", "pending"}:
        for upload in uploads:
            if (
                int(upload.size_bytes or 0) > 0
                and int(upload.uploaded_bytes or 0) <= 0
                and (
                    upload.finalized_at
                    or upload.status in {"uploaded", "queued", "processing", "completed", "failed"}
                )
            ):
                upload.uploaded_bytes = int(upload.size_bytes)
            if (
                int(upload.total_chunks or 0) > 0
                and int(upload.uploaded_chunks or 0) <= 0
                and int(upload.uploaded_bytes or 0) >= int(upload.size_bytes or 0)
            ):
                upload.uploaded_chunks = int(upload.total_chunks)
            batch.uploaded_bytes += int(upload.uploaded_bytes or 0)
            if int(upload.uploaded_bytes or 0) >= int(upload.size_bytes or 0):
                batch.uploaded_files += 1
        return

    for upload in uploads:
        state = get_runtime_state(upload)
        sync_upload_model(upload, state)
        batch.uploaded_bytes += upload.uploaded_bytes
        if upload.uploaded_bytes >= upload.size_bytes:
            batch.uploaded_files += 1


def upload_chunk(upload: UploadFile, chunk_index: int, start_byte: int, payload: bytes) -> tuple[dict, bool]:
    with _lock_for(upload):
        state = ensure_runtime(upload)
        chunk_size = int(state["chunkSize"])
        total_chunks = int(state["totalChunks"])
        size_bytes = int(state["sizeBytes"])
        if chunk_index < 0 or chunk_index >= total_chunks:
            raise ValueError("Chunk index out of range")
        expected_start_byte = chunk_index * chunk_size
        if start_byte != expected_start_byte:
            raise RuntimeError("Chunk offset mismatch")
        end_byte = start_byte + len(payload)
        if end_byte > size_bytes:
            raise ValueError("Chunk exceeds file size")

        bitmap_path = _bitmap_path(upload)
        with bitmap_path.open("r+b") as bitmap_handle:
            bitmap_handle.seek(chunk_index)
            existing = bitmap_handle.read(1)
            if existing == b"\x01":
                state["receivedChunkIndexes"] = _read_received_indexes(bitmap_path, total_chunks)
                return state, False

            destination = Path(upload.temp_path)
            ensure_parent(destination)
            mode = "r+b" if destination.exists() else "w+b"
            with destination.open(mode) as target:
                target.seek(start_byte)
                target.write(payload)

            bitmap_handle.seek(chunk_index)
            bitmap_handle.write(b"\x01")

        state["uploadedBytes"] = min(int(state["uploadedBytes"]) + len(payload), size_bytes)
        state["uploadedChunks"] = min(int(state["uploadedChunks"]) + 1, total_chunks)
        state["updatedAt"] = datetime.utcnow().isoformat() + "Z"
        _write_state(_meta_path(upload), state)
        return state, True


def finalize_upload(upload: UploadFile) -> dict:
    with _lock_for(upload):
        state = ensure_runtime(upload)
        state["receivedChunkIndexes"] = _read_received_indexes(_bitmap_path(upload), state["totalChunks"])
        return state
