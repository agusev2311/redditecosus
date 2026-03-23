from __future__ import annotations

from sqlalchemy import text

from ..extensions import db


SQLITE_COLUMN_MIGRATIONS = {
    "upload_batch": {
        "owner_id": "INTEGER",
        "stored_items": "INTEGER NOT NULL DEFAULT 0",
        "duplicate_items": "INTEGER NOT NULL DEFAULT 0",
        "failed_items": "INTEGER NOT NULL DEFAULT 0",
        "processed_bytes": "BIGINT NOT NULL DEFAULT 0",
        "error_message": "TEXT",
        "started_processing_at": "DATETIME",
        "finished_at": "DATETIME",
    },
    "tag": {
        "avatar_url": "TEXT",
        "created_by_id": "INTEGER",
        "gradient_colors": "TEXT",
        "gradient_angle": "INTEGER NOT NULL DEFAULT 135",
    },
    "upload_file": {
        "client_file_id": "TEXT",
        "chunk_size": "INTEGER NOT NULL DEFAULT 0",
        "total_chunks": "INTEGER NOT NULL DEFAULT 0",
        "uploaded_chunks": "INTEGER NOT NULL DEFAULT 0",
        "uploaded_bytes": "BIGINT NOT NULL DEFAULT 0",
        "upload_source": "TEXT NOT NULL DEFAULT 'web'",
        "finalized_at": "DATETIME",
        "error_message": "TEXT",
    },
    "media_item": {
        "owner_id": "INTEGER",
        "upload_batch_id": "TEXT",
        "canonical_media_id": "INTEGER",
        "perceptual_hash": "TEXT",
        "note": "TEXT",
        "is_encrypted": "BOOLEAN NOT NULL DEFAULT 0",
        "is_duplicate": "BOOLEAN NOT NULL DEFAULT 0",
    }
}


def _table_exists(connection, table_name: str) -> bool:
    result = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name = :table_name"),
        {"table_name": table_name},
    ).fetchone()
    return bool(result)


def _existing_columns(connection, table_name: str) -> set[str]:
    if not _table_exists(connection, table_name):
        return set()
    return {
        row[1] for row in connection.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()
    }


def _first_user_id(connection) -> int | None:
    if not _table_exists(connection, "user"):
        return None
    row = connection.execute(text('SELECT id FROM "user" ORDER BY id ASC LIMIT 1')).fetchone()
    return int(row[0]) if row else None


def ensure_sqlite_schema() -> None:
    engine = db.engine
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        for table_name, required_columns in SQLITE_COLUMN_MIGRATIONS.items():
            existing = _existing_columns(connection, table_name)
            if not existing:
                continue
            for column_name, column_sql in required_columns.items():
                if column_name in existing:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
                )

        media_item_columns = _existing_columns(connection, "media_item")
        default_owner_id = _first_user_id(connection)
        if "owner_id" in media_item_columns and default_owner_id is not None:
            connection.execute(
                text("UPDATE media_item SET owner_id = :owner_id WHERE owner_id IS NULL"),
                {"owner_id": default_owner_id},
            )

        upload_batch_columns = _existing_columns(connection, "upload_batch")
        if "owner_id" in upload_batch_columns and default_owner_id is not None:
            connection.execute(
                text("UPDATE upload_batch SET owner_id = :owner_id WHERE owner_id IS NULL"),
                {"owner_id": default_owner_id},
            )

        tag_columns = _existing_columns(connection, "tag")
        if "created_by_id" in tag_columns and default_owner_id is not None:
            connection.execute(
                text("UPDATE tag SET created_by_id = :owner_id WHERE created_by_id IS NULL"),
                {"owner_id": default_owner_id},
            )


def apply_sqlite_compat_migrations() -> None:
    ensure_sqlite_schema()
