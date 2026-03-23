import os
from pathlib import Path


def _path_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


class Config:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    DATA_ROOT = _path_env("MEDIAHUB_DATA_ROOT", PROJECT_ROOT / "data")
    STORAGE_ROOT = DATA_ROOT / "storage"
    ORIGINALS_ROOT = STORAGE_ROOT / "originals"
    PREVIEWS_ROOT = STORAGE_ROOT / "previews"
    IMPORTS_ROOT = DATA_ROOT / "imports"
    EXPORTS_ROOT = DATA_ROOT / "exports"
    BACKUPS_ROOT = DATA_ROOT / "backups"
    DATABASE_PATH = DATA_ROOT / "mediahub.db"

    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH.as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.getenv("MEDIAHUB_SECRET_KEY", "change-me-before-production")
    TOKEN_TTL_SECONDS = int(os.getenv("MEDIAHUB_TOKEN_TTL_SECONDS", "2592000"))
    MAX_CONTENT_LENGTH = int(
        os.getenv("MEDIAHUB_MAX_CONTENT_LENGTH", str(8 * 1024 * 1024 * 1024))
    )

    FRONTEND_BASE_URL = os.getenv("MEDIAHUB_FRONTEND_BASE_URL", "http://localhost:8080")
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "MEDIAHUB_CORS_ORIGINS",
            "http://localhost:5173,http://localhost:4173,http://localhost:8080",
        ).split(",")
        if origin.strip()
    ]

    MEDIA_ENCRYPTION_PASSPHRASE = os.getenv("MEDIAHUB_ENCRYPTION_PASSPHRASE", "").strip()
    LOW_DISK_THRESHOLD_GB = int(os.getenv("MEDIAHUB_LOW_DISK_THRESHOLD_GB", "20"))
    LOW_DISK_THRESHOLD_PERCENT = int(os.getenv("MEDIAHUB_LOW_DISK_THRESHOLD_PERCENT", "10"))
    MONITOR_POLL_SECONDS = int(os.getenv("MEDIAHUB_MONITOR_POLL_SECONDS", "180"))
    TELEGRAM_CHUNK_BYTES = int(
        os.getenv("MEDIAHUB_TELEGRAM_CHUNK_BYTES", str(48 * 1024 * 1024))
    )
    TELEGRAM_POLL_TIMEOUT_SECONDS = int(
        os.getenv("MEDIAHUB_TELEGRAM_POLL_TIMEOUT_SECONDS", "25")
    )
    TELEGRAM_POLL_IDLE_SECONDS = int(
        os.getenv("MEDIAHUB_TELEGRAM_POLL_IDLE_SECONDS", "5")
    )
    TELEGRAM_API_BASE_URL = os.getenv("MEDIAHUB_TELEGRAM_API_BASE_URL", "https://api.telegram.org")
    RESUMABLE_UPLOAD_CHUNK_BYTES = int(
        os.getenv("MEDIAHUB_RESUMABLE_UPLOAD_CHUNK_BYTES", str(8 * 1024 * 1024))
    )

    EXPORT_INCLUDE_PASSWORD_HASHES = (
        os.getenv("MEDIAHUB_EXPORT_INCLUDE_PASSWORD_HASHES", "true").lower() == "true"
    )
