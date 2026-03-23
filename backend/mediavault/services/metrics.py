from __future__ import annotations

import os
import time
from pathlib import Path

import psutil
from flask import current_app

from .settings import get_bool_setting, get_int_setting

_network_cache = {"time": None, "sent": None, "recv": None}
_disk_cache = {"time": 0.0, "payload": None}


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        root_path = Path(root)
        for filename in files:
            try:
                total += (root_path / filename).stat().st_size
            except OSError:
                continue
    return total


def _network_snapshot():
    counters = psutil.net_io_counters()
    now = time.time()
    previous_time = _network_cache["time"]
    previous_sent = _network_cache["sent"]
    previous_recv = _network_cache["recv"]
    _network_cache.update({"time": now, "sent": counters.bytes_sent, "recv": counters.bytes_recv})
    if previous_time is None:
        return {
            "bytesSent": counters.bytes_sent,
            "bytesRecv": counters.bytes_recv,
            "sendRate": 0,
            "recvRate": 0,
        }
    elapsed = max(now - previous_time, 1e-6)
    return {
        "bytesSent": counters.bytes_sent,
        "bytesRecv": counters.bytes_recv,
        "sendRate": max(counters.bytes_sent - previous_sent, 0) / elapsed,
        "recvRate": max(counters.bytes_recv - previous_recv, 0) / elapsed,
    }


def _disk_categories():
    now = time.time()
    if _disk_cache["payload"] and now - _disk_cache["time"] < 20:
        return _disk_cache["payload"]
    data_root = Path(current_app.config["DATA_ROOT"])
    categories = {
        "media": _dir_size(Path(current_app.config["ORIGINALS_ROOT"])),
        "previews": _dir_size(Path(current_app.config["PREVIEWS_ROOT"])),
        "imports": _dir_size(Path(current_app.config["IMPORTS_ROOT"])),
        "exports": _dir_size(Path(current_app.config["EXPORTS_ROOT"])),
        "backups": _dir_size(Path(current_app.config["BACKUPS_ROOT"])),
        "database": Path(current_app.config["DATABASE_PATH"]).stat().st_size
        if Path(current_app.config["DATABASE_PATH"]).exists()
        else 0,
    }
    known = sum(categories.values())
    total_root = _dir_size(data_root)
    categories["other"] = max(total_root - known, 0)
    payload = [{"label": key, "sizeBytes": value} for key, value in categories.items()]
    _disk_cache.update({"time": now, "payload": payload})
    return payload


def evaluate_disk_alert():
    usage = psutil.disk_usage(str(current_app.config["DATA_ROOT"]))
    free_gb = usage.free / (1024 ** 3)
    free_percent = 100 - usage.percent
    threshold_gb = get_int_setting("storage.warning_gb", current_app.config["LOW_DISK_THRESHOLD_GB"])
    threshold_percent = get_int_setting(
        "storage.warning_percent",
        current_app.config["LOW_DISK_THRESHOLD_PERCENT"],
    )
    active = free_gb <= threshold_gb or free_percent <= threshold_percent
    return {
        "active": active,
        "freeGb": round(free_gb, 2),
        "freePercent": round(free_percent, 2),
        "thresholdGb": threshold_gb,
        "thresholdPercent": threshold_percent,
        "message": (
            f"Disk space is running low: {free_gb:.1f} GB free ({free_percent:.1f}%)."
            if active
            else None
        ),
        "uploadsBlockedForUsers": active,
        "telegramNotificationsEnabled": get_bool_setting("telegram.auto_disk_alerts", True),
    }


def get_metrics_snapshot():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(current_app.config["DATA_ROOT"]))
    return {
        "cpu": {"percent": psutil.cpu_percent(interval=None)},
        "memory": {
            "percent": memory.percent,
            "usedBytes": memory.used,
            "totalBytes": memory.total,
            "availableBytes": memory.available,
        },
        "disk": {
            "percent": disk.percent,
            "usedBytes": disk.used,
            "freeBytes": disk.free,
            "totalBytes": disk.total,
            "categories": _disk_categories(),
        },
        "network": _network_snapshot(),
        "alerts": {"disk": evaluate_disk_alert()},
    }
