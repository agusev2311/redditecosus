from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import struct
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from PIL import Image, ImageOps, UnidentifiedImageError

from ..models import MediaItem
from ..utils import ensure_parent

ENCRYPTION_MAGIC = b"MHUB1"
CHUNK_SIZE = 64 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".wmv"}


def ensure_storage_tree() -> None:
    from flask import current_app

    for key in (
        "DATA_ROOT",
        "STORAGE_ROOT",
        "ORIGINALS_ROOT",
        "PREVIEWS_ROOT",
        "IMPORTS_ROOT",
        "EXPORTS_ROOT",
        "BACKUPS_ROOT",
    ):
        Path(current_app.config[key]).mkdir(parents=True, exist_ok=True)


def guess_media_type(filename: str, mime_type: str | None = None) -> str | None:
    mime = mime_type or mimetypes.guess_type(filename)[0] or ""
    suffix = Path(filename).suffix.lower()
    if mime.startswith("image/") or suffix in IMAGE_EXTENSIONS:
        return "image"
    if mime.startswith("video/") or suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def is_archive_file(filename: str) -> bool:
    lower = filename.lower()
    return lower.endswith(".zip") or lower.endswith(".tar") or lower.endswith(".tar.gz") or lower.endswith(".tgz")


def iter_plain_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            yield chunk


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for chunk in iter_plain_chunks(path):
        digest.update(chunk)
    return digest.hexdigest()


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _use_encryption() -> bool:
    from flask import current_app

    return bool(current_app.config["MEDIA_ENCRYPTION_PASSPHRASE"])


def _relative_media_path(prefix: str, hash_hex: str, suffix: str) -> Path:
    safe_suffix = suffix.lower() if suffix else ".bin"
    name = f"{hash_hex}{safe_suffix}"
    if _use_encryption():
        name = f"{name}.vault"
    return Path(prefix) / hash_hex[:2] / hash_hex[2:4] / name


def encrypt_file(src: Path, dest: Path) -> None:
    from flask import current_app

    passphrase = current_app.config["MEDIA_ENCRYPTION_PASSPHRASE"]
    ensure_parent(dest)
    salt = os.urandom(16)
    aes = AESGCM(_derive_key(passphrase, salt))
    with src.open("rb") as source, dest.open("wb") as target:
        target.write(ENCRYPTION_MAGIC)
        target.write(salt)
        target.write(struct.pack(">I", CHUNK_SIZE))
        while True:
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            nonce = os.urandom(12)
            ciphertext = aes.encrypt(nonce, chunk, None)
            target.write(nonce)
            target.write(struct.pack(">I", len(ciphertext)))
            target.write(ciphertext)


def iter_decrypted_chunks(path: Path) -> Iterator[bytes]:
    from flask import current_app

    passphrase = current_app.config["MEDIA_ENCRYPTION_PASSPHRASE"]
    with path.open("rb") as handle:
        magic = handle.read(len(ENCRYPTION_MAGIC))
        if magic != ENCRYPTION_MAGIC:
            raise ValueError("Invalid encrypted file header")
        salt = handle.read(16)
        handle.read(4)
        aes = AESGCM(_derive_key(passphrase, salt))
        while True:
            nonce = handle.read(12)
            if not nonce:
                break
            size_bytes = handle.read(4)
            if len(size_bytes) != 4:
                break
            length = struct.unpack(">I", size_bytes)[0]
            ciphertext = handle.read(length)
            yield aes.decrypt(nonce, ciphertext, None)


def iter_storage_chunks(relative_path: str, encrypted: bool) -> Iterator[bytes]:
    from flask import current_app

    absolute = Path(current_app.config["DATA_ROOT"]) / relative_path
    if encrypted:
        yield from iter_decrypted_chunks(absolute)
    else:
        yield from iter_plain_chunks(absolute)


@contextmanager
def materialize_storage_path(relative_path: str, encrypted: bool):
    from flask import current_app

    absolute = Path(current_app.config["DATA_ROOT"]) / relative_path
    if not encrypted:
        yield absolute
        return

    suffix = "".join(Path(relative_path).suffixes) or ".bin"
    temp_file = tempfile.NamedTemporaryFile(
        delete=False,
        dir=current_app.config["IMPORTS_ROOT"],
        suffix=suffix,
    )
    temp_path = Path(temp_file.name)
    try:
        with temp_file:
            for chunk in iter_storage_chunks(relative_path, encrypted):
                temp_file.write(chunk)
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def save_uploaded_stream(file_storage, destination: Path) -> int:
    ensure_parent(destination)
    total = 0
    with destination.open("wb") as handle:
        while chunk := file_storage.stream.read(CHUNK_SIZE):
            total += len(chunk)
            handle.write(chunk)
    return total


def upload_marker_dir(destination: Path) -> Path:
    return destination.with_name(f"{destination.name}.parts")


def collect_upload_chunk_state(
    destination: Path,
    chunk_size: int,
    total_chunks: int,
    size_bytes: int,
) -> tuple[list[int], int]:
    marker_dir = upload_marker_dir(destination)
    if not marker_dir.exists():
        actual_size = destination.stat().st_size if destination.exists() else 0
        if actual_size <= 0 or chunk_size <= 0:
            return [], 0
        contiguous_chunks = min(total_chunks or 0, (actual_size + chunk_size - 1) // chunk_size)
        return list(range(contiguous_chunks)), min(actual_size, size_bytes or actual_size)

    chunk_indexes: list[int] = []
    uploaded_bytes = 0
    for marker in marker_dir.iterdir():
        if not marker.is_file() or marker.suffix != ".part":
            continue
        try:
            chunk_index = int(marker.stem)
            chunk_bytes = int(marker.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            continue
        if chunk_index < 0:
            continue
        chunk_indexes.append(chunk_index)
        uploaded_bytes += max(chunk_bytes, 0)
    chunk_indexes.sort()
    return chunk_indexes, min(uploaded_bytes, size_bytes or uploaded_bytes)


def write_upload_chunk(destination: Path, start_byte: int, chunk_index: int, payload: bytes) -> bool:
    ensure_parent(destination)
    marker_dir = upload_marker_dir(destination)
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / f"{chunk_index}.part"
    if marker_path.exists():
        return False

    mode = "r+b" if destination.exists() else "wb"
    with destination.open(mode) as handle:
        handle.seek(start_byte)
        handle.write(payload)

    marker_path.write_text(str(len(payload)), encoding="utf-8")
    return True


def append_upload_chunk(destination: Path, start_byte: int, payload: bytes) -> tuple[int, int]:
    ensure_parent(destination)
    mode = "r+b" if destination.exists() else "wb"
    with destination.open(mode) as handle:
        handle.seek(0, os.SEEK_END)
        current_size = handle.tell()
        if current_size != start_byte:
            return current_size, current_size
        handle.write(payload)
        return current_size, handle.tell()


def store_original(temp_path: Path, hash_hex: str, original_filename: str) -> str:
    from flask import current_app

    suffix = Path(original_filename).suffix or ".bin"
    relative = _relative_media_path("storage/originals", hash_hex, suffix)
    absolute = Path(current_app.config["DATA_ROOT"]) / relative
    if absolute.exists():
        temp_path.unlink(missing_ok=True)
        return relative.as_posix()
    if _use_encryption():
        encrypt_file(temp_path, absolute)
        temp_path.unlink(missing_ok=True)
    else:
        ensure_parent(absolute)
        shutil.move(str(temp_path), str(absolute))
    return relative.as_posix()


def store_preview(temp_path: Path, hash_hex: str) -> str:
    from flask import current_app

    relative = _relative_media_path("storage/previews", hash_hex, ".jpg")
    absolute = Path(current_app.config["DATA_ROOT"]) / relative
    if absolute.exists():
        temp_path.unlink(missing_ok=True)
        return relative.as_posix()
    if _use_encryption():
        encrypt_file(temp_path, absolute)
        temp_path.unlink(missing_ok=True)
    else:
        ensure_parent(absolute)
        shutil.move(str(temp_path), str(absolute))
    return relative.as_posix()


def delete_storage_if_unreferenced(relative_path: str | None, media_id_to_ignore: int | None = None) -> None:
    if not relative_path:
        return
    query = MediaItem.query.filter_by(storage_path=relative_path)
    if media_id_to_ignore is not None:
        query = query.filter(MediaItem.id != media_id_to_ignore)
    if query.count():
        return
    from flask import current_app

    absolute = Path(current_app.config["DATA_ROOT"]) / relative_path
    absolute.unlink(missing_ok=True)


def delete_preview_if_unreferenced(relative_path: str | None, media_id_to_ignore: int | None = None) -> None:
    if not relative_path:
        return
    query = MediaItem.query.filter_by(preview_path=relative_path)
    if media_id_to_ignore is not None:
        query = query.filter(MediaItem.id != media_id_to_ignore)
    if query.count():
        return
    from flask import current_app

    absolute = Path(current_app.config["DATA_ROOT"]) / relative_path
    absolute.unlink(missing_ok=True)


def generate_image_preview(source_path: Path, output_path: Path) -> tuple[int | None, int | None]:
    ensure_parent(output_path)
    with Image.open(source_path) as image:
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        image.thumbnail((1280, 1280))
        image.convert("RGB").save(output_path, format="JPEG", quality=84, optimize=True)
        return width, height


def inspect_image_size(source_path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(source_path) as image:
            return image.size
    except (UnidentifiedImageError, OSError):
        return None, None


def build_streaming_response(relative_path: str, encrypted: bool, mime_type: str, download_name: str | None = None):
    from flask import Response, current_app, send_file, stream_with_context

    absolute = Path(current_app.config["DATA_ROOT"]) / relative_path
    if not encrypted:
        return send_file(
            absolute,
            mimetype=mime_type,
            as_attachment=bool(download_name),
            download_name=download_name,
            conditional=True,
            etag=True,
            max_age=604800,
        )

    headers = {}
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return Response(
        stream_with_context(iter_storage_chunks(relative_path, encrypted)),
        mimetype=mime_type,
        headers=headers,
    )
