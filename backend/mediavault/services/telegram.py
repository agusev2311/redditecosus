from __future__ import annotations

from pathlib import Path

import requests

from .settings import get_bool_setting, get_setting


def telegram_configured() -> bool:
    return bool(get_setting("telegram.bot_token")) and bool(get_setting("telegram.chat_id"))


def send_message(text: str) -> dict:
    token = get_setting("telegram.bot_token")
    chat_id = get_setting("telegram.chat_id")
    if not token or not chat_id:
        raise RuntimeError("Telegram is not configured")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def send_document_chunks(file_path: str, caption_prefix: str | None = None) -> int:
    from flask import current_app

    token = get_setting("telegram.bot_token")
    chat_id = get_setting("telegram.chat_id")
    if not token or not chat_id:
        raise RuntimeError("Telegram is not configured")

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
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": caption},
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
