from __future__ import annotations

from sqlalchemy import text

from ..extensions import db


SQLITE_COLUMN_MIGRATIONS = {
    "tag": {
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
    },
    "media_item": {
        "perceptual_hash": "TEXT",
    }
}


def ensure_sqlite_schema() -> None:
    engine = db.engine
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        for table_name, required_columns in SQLITE_COLUMN_MIGRATIONS.items():
            existing = {
                row[1] for row in connection.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()
            }
            for column_name, column_sql in required_columns.items():
                if column_name in existing:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
                )


def apply_sqlite_compat_migrations() -> None:
    ensure_sqlite_schema()
