from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests
from flask import current_app

from ..extensions import db
from ..models import UploadBatch, UploadFile, User
from .settings import get_bool_setting, get_int_setting, get_setting, set_setting
from .storage import is_archive_file

OFFICIAL_BOT_API_DOWNLOAD_LIMIT_BYTES = 20 * 1024 * 1024


def telegram_configured() -> bool:
    return bool(get_setting("telegram.bot_token")) and bool(get_setting("telegram.chat_id"))


def telegram_bot_token() -> str:
    return (get_setting("telegram.bot_token") or "").strip()


def telegram_polling_enabled() -> bool:
    return get_bool_setting("telegram.polling_enabled", True)


def telegram_api_base_url() -> str:
    return current_app.config["TELEGRAM_API_BASE_URL"].rstrip("/")


def telegram_uses_local_api_server() -> bool:
    return telegram_api_base_url() != "https://api.telegram.org"


def _api_request(method: str, endpoint: str, **kwargs) -> dict:
    token = telegram_bot_token()
    if not token:
        raise RuntimeError("Telegram bot token is not configured")
    response = requests.request(
        method,
        f"{telegram_api_base_url()}/bot{token}/{endpoint}",
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )
    payload = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        description = payload.get("description") if isinstance(payload, dict) else None
        raise RuntimeError(description or f"Telegram API HTTP {response.status_code} at {endpoint}")
    if not payload.get("ok", False):
        raise RuntimeError(payload.get("description") or f"Telegram API error at {endpoint}")
    return payload


def send_chat_message(chat_id: str | int, text: str) -> dict:
    return _api_request(
        "POST",
        "sendMessage",
        data={"chat_id": str(chat_id), "text": text},
    )


def send_message(text: str) -> dict:
    chat_id = get_setting("telegram.chat_id")
    if not chat_id:
        raise RuntimeError("Telegram chat id is not configured")
    return send_chat_message(chat_id, text)


def send_document_chunks(file_path: str, caption_prefix: str | None = None) -> int:
    chat_id = get_setting("telegram.chat_id")
    if not chat_id:
        raise RuntimeError("Telegram chat id is not configured")

    chunk_size = current_app.config["TELEGRAM_CHUNK_BYTES"]
    source = Path(file_path)
    sent = 0
    with source.open("rb") as handle:
        index = 1
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            part_path = Path(current_app.config["BACKUPS_ROOT"]) / f"{source.name}.part{index:03d}"
            part_path.write_bytes(chunk)
            caption = caption_prefix or f"MediaHub backup chunk {index}"
            if source.stat().st_size > chunk_size:
                caption = f"{caption} ({index})"
            with part_path.open("rb") as part_file:
                response = requests.post(
                    f"{telegram_api_base_url()}/bot{telegram_bot_token()}/sendDocument",
                    data={"chat_id": str(chat_id), "caption": caption},
                    files={"document": (part_path.name, part_file)},
                    timeout=180,
                )
                response.raise_for_status()
            part_path.unlink(missing_ok=True)
            sent += 1
            index += 1
    return sent


def maybe_send_disk_alert(message: str) -> bool:
    if not get_bool_setting("telegram.auto_disk_alerts", True):
        return False
    if not telegram_configured():
        return False
    send_message(message)
    return True


def _get_updates(offset: int | None = None) -> list[dict]:
    params = {"timeout": current_app.config["TELEGRAM_POLL_TIMEOUT_SECONDS"]}
    if offset is not None:
        params["offset"] = offset
    payload = _api_request("GET", "getUpdates", params=params, timeout=params["timeout"] + 10)
    return payload.get("result", [])


def _download_file(file_id: str, destination: Path) -> None:
    file_payload = _api_request("GET", "getFile", params={"file_id": file_id})
    file_path = file_payload["result"]["file_path"]
    local_path = Path(file_path)
    if local_path.is_absolute():
        if local_path.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, destination)
            return
        raise RuntimeError(
            "Telegram local Bot API returned a local file path that is not mounted into the backend container"
        )
    response = requests.get(
        f"{telegram_api_base_url()}/file/bot{telegram_bot_token()}/{file_path}",
        timeout=180,
        stream=True,
    )
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        for chunk in response.iter_content(1024 * 512):
            if chunk:
                handle.write(chunk)


def _authorized_chat_id() -> str:
    return str(get_setting("telegram.chat_id") or "").strip()


def _admin_user() -> User | None:
    return User.query.filter_by(role="admin", is_active=True).order_by(User.id.asc()).first()


def _ingest_archive_from_message(chat_id: str, message: dict) -> None:
    from .jobs import launch_batch_job

    document = message["document"]
    filename = Path(document.get("file_name") or "archive.bin").name
    if not is_archive_file(filename):
        send_chat_message(
            chat_id,
            "Я умею принимать архивы .zip, .tar, .tar.gz и .tgz. Отправьте архив как документ.",
        )
        return

    file_size = int(document.get("file_size") or 0)
    if file_size > OFFICIAL_BOT_API_DOWNLOAD_LIMIT_BYTES and not telegram_uses_local_api_server():
        send_chat_message(
            chat_id,
            "Этот архив слишком большой для обычного Telegram Bot API. "
            "Сейчас Telegram позволяет боту скачать только файлы до 20 MB через cloud Bot API. "
            "Для больших архивов нужен локальный Telegram Bot API server.",
        )
        return

    admin_user = _admin_user()
    if not admin_user:
        send_chat_message(chat_id, "Админ-пользователь ещё не создан в MediaHub.")
        return

    message_key = f"telegram-{chat_id}-{message['message_id']}"
    if UploadFile.query.filter_by(client_file_id=message_key).first():
        send_chat_message(chat_id, "Этот архив уже был принят в обработку.")
        return

    batch = UploadBatch(
        owner_id=admin_user.id,
        client_total_files=1,
        uploaded_files=1,
        total_bytes=int(document.get("file_size") or 0),
        uploaded_bytes=int(document.get("file_size") or 0),
        status="queued",
        temp_dir=(Path(current_app.config["IMPORTS_ROOT"]) / f"telegram-{uuid4()}").as_posix(),
    )
    Path(batch.temp_dir).mkdir(parents=True, exist_ok=True)
    db.session.add(batch)
    db.session.flush()

    try:
        downloaded = Path(batch.temp_dir) / filename
        _download_file(document["file_id"], downloaded)
        size_bytes = downloaded.stat().st_size
        upload = UploadFile(
            batch_id=batch.id,
            client_file_id=message_key,
            original_filename=filename,
            temp_path=downloaded.as_posix(),
            mime_type=document.get("mime_type") or "application/octet-stream",
            size_bytes=size_bytes,
            chunk_size=size_bytes,
            total_chunks=1,
            uploaded_chunks=1,
            uploaded_bytes=size_bytes,
            upload_source="telegram",
            finalized_at=datetime.utcnow(),
            status="uploaded",
        )
        db.session.add(upload)
        batch.uploaded_bytes = size_bytes
        batch.uploaded_files = 1
        db.session.commit()

        launch_batch_job(current_app._get_current_object(), batch.id)
        send_chat_message(
            chat_id,
            f"Архив `{filename}` принят. Импорт запущен, batch: `{batch.id[:8]}`.",
        )
    except Exception as exc:
        db.session.rollback()
        shutil.rmtree(batch.temp_dir, ignore_errors=True)
        send_chat_message(chat_id, f"Не удалось принять архив: {exc}")


def _handle_message(message: dict) -> None:
    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    configured_chat_id = _authorized_chat_id()

    if text.startswith("/start"):
        status = (
            "Этот чат уже привязан к MediaHub."
            if configured_chat_id and configured_chat_id == chat_id
            else "Этот чат пока не привязан. Вставьте этот chat id в настройки MediaHub."
        )
        send_chat_message(
            chat_id,
            f"MediaHub bot online.\nchat_id: {chat_id}\n{status}\n"
            "Можно отправлять /start и архивы .zip/.tar/.tgz как документ.",
        )
        return

    if text.startswith("/help"):
        send_chat_message(
            chat_id,
            "Команды:\n/start - показать chat id\n/help - краткая справка\n"
            "Также можно прислать архив .zip/.tar/.tgz документом для импорта в MediaHub.",
        )
        return

    if "document" not in message:
        return

    if not configured_chat_id or configured_chat_id != chat_id:
        send_chat_message(
            chat_id,
            f"Этот чат не авторизован для импорта. chat_id: {chat_id}",
        )
        return

    _ingest_archive_from_message(chat_id, message)


def process_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    _handle_message(message)


def poll_once() -> int:
    if not telegram_polling_enabled() or not telegram_bot_token():
        time.sleep(current_app.config["TELEGRAM_POLL_IDLE_SECONDS"])
        return get_int_setting("telegram.last_update_id", 0)

    last_update_id = get_int_setting("telegram.last_update_id", 0)
    updates = _get_updates(offset=last_update_id + 1 if last_update_id else None)
    max_update_id = last_update_id
    for update in updates:
        max_update_id = max(max_update_id, int(update["update_id"]))
        try:
            process_update(update)
        except Exception as exc:
            current_app.logger.warning(
                "Telegram update %s failed: %s",
                update.get("update_id"),
                exc,
            )
            db.session.rollback()
    if max_update_id != last_update_id:
        set_setting("telegram.last_update_id", max_update_id)
        db.session.commit()
    return max_update_id


def clear_downloaded_parts(temp_dir: Path) -> None:
    shutil.rmtree(temp_dir, ignore_errors=True)
