from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.utcnow()


media_tags = db.Table(
    "media_tags",
    db.Column("media_id", db.Integer, db.ForeignKey("media_item.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class User(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    media_items = db.relationship("MediaItem", back_populates="owner", lazy="dynamic")
    upload_batches = db.relationship("UploadBatch", back_populates="owner", lazy="dynamic")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Tag(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    style_mode = db.Column(db.String(20), nullable=False, default="gradient")
    color_start = db.Column(db.String(32), nullable=False, default="#7c3aed")
    color_end = db.Column(db.String(32), nullable=False, default="#10b981")
    text_color = db.Column(db.String(32), nullable=False, default="#f8fafc")
    avatar_url = db.Column(db.String(512), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)


class UploadBatch(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    client_total_files = db.Column(db.Integer, nullable=False, default=0)
    uploaded_files = db.Column(db.Integer, nullable=False, default=0)
    total_items = db.Column(db.Integer, nullable=False, default=0)
    processed_items = db.Column(db.Integer, nullable=False, default=0)
    stored_items = db.Column(db.Integer, nullable=False, default=0)
    duplicate_items = db.Column(db.Integer, nullable=False, default=0)
    failed_items = db.Column(db.Integer, nullable=False, default=0)
    total_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    uploaded_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    processed_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="uploading", index=True)
    error_message = db.Column(db.Text, nullable=True)
    temp_dir = db.Column(db.String(1024), nullable=False)
    started_processing_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship("User", back_populates="upload_batches")
    files = db.relationship(
        "UploadFile",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )


class UploadFile(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    batch_id = db.Column(db.String(36), db.ForeignKey("upload_batch.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(512), nullable=False)
    temp_path = db.Column(db.String(1024), nullable=False)
    mime_type = db.Column(db.String(255), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="uploaded")
    error_message = db.Column(db.Text, nullable=True)

    batch = db.relationship("UploadBatch", back_populates="files")


class MediaItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    upload_batch_id = db.Column(
        db.String(36), db.ForeignKey("upload_batch.id"), nullable=True, index=True
    )
    canonical_media_id = db.Column(db.Integer, db.ForeignKey("media_item.id"), nullable=True)

    original_filename = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(1024), nullable=False)
    preview_path = db.Column(db.String(1024), nullable=True)
    media_type = db.Column(db.String(20), nullable=False, index=True)
    mime_type = db.Column(db.String(255), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    duration_seconds = db.Column(db.Float, nullable=True)
    sha256_hash = db.Column(db.String(64), nullable=False, index=True)
    note = db.Column(db.Text, nullable=True)
    is_encrypted = db.Column(db.Boolean, nullable=False, default=False)
    is_duplicate = db.Column(db.Boolean, nullable=False, default=False, index=True)

    owner = db.relationship("User", back_populates="media_items")
    tags = db.relationship("Tag", secondary=media_tags, lazy="joined")
    canonical_media = db.relationship("MediaItem", remote_side=[id], backref="duplicates")

    @property
    def canonical_root(self) -> "MediaItem":
        return self.canonical_media or self


class ShareLink(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    media_id = db.Column(db.Integer, db.ForeignKey("media_item.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    max_views = db.Column(db.Integer, nullable=True)
    view_count = db.Column(db.Integer, nullable=False, default=0)
    burn_after_read = db.Column(db.Boolean, nullable=False, default=False)
    is_revoked = db.Column(db.Boolean, nullable=False, default=False)
    last_viewed_at = db.Column(db.DateTime, nullable=True)

    media = db.relationship("MediaItem")
    created_by = db.relationship("User")


class ExportJob(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(40), nullable=False, default="queued", index=True)
    archive_path = db.Column(db.String(1024), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    pushed_to_telegram = db.Column(db.Boolean, nullable=False, default=False)
    error_message = db.Column(db.Text, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship("User")


class AppSetting(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)


class AlertState(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    last_message = db.Column(db.Text, nullable=True)
