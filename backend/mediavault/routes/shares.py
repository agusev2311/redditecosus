from __future__ import annotations

from datetime import datetime, timedelta
from secrets import token_urlsafe

from flask import Blueprint, jsonify, request

from ..auth import auth_required, get_current_user
from ..extensions import db
from ..models import MediaItem, ShareLink
from ..services.serializers import serialize_media, serialize_share
from ..services.storage import build_streaming_response

bp = Blueprint("shares", __name__)


def _share_scope():
    return ShareLink.query.filter_by(created_by_id=get_current_user().id)


def _media_scope():
    return MediaItem.query.filter_by(owner_id=get_current_user().id)


def _public_share(token: str):
    share = ShareLink.query.filter_by(token=token).first_or_404()
    if share.is_revoked:
        return None
    if share.expires_at and share.expires_at < datetime.utcnow():
        return None
    if share.max_views is not None and share.view_count >= share.max_views:
        return None
    return share


@bp.get("")
@auth_required()
def list_shares():
    shares = _share_scope().order_by(ShareLink.created_at.desc()).all()
    return jsonify({"items": [serialize_share(share) for share in shares]})


@bp.post("")
@auth_required()
def create_share():
    payload = request.get_json(force=True) or {}
    media = _media_scope().filter_by(id=int(payload.get("mediaId") or 0)).first_or_404()
    expires_hours = int(payload.get("expiresInHours") or 24)
    share = ShareLink(
        token=token_urlsafe(24),
        media_id=media.id,
        created_by_id=get_current_user().id,
        expires_at=datetime.utcnow() + timedelta(hours=expires_hours) if expires_hours > 0 else None,
        max_views=(int(payload["maxViews"]) if payload.get("maxViews") is not None else None),
        burn_after_read=bool(payload.get("burnAfterRead")),
        is_revoked=False,
    )
    db.session.add(share)
    db.session.commit()
    return jsonify({"item": serialize_share(share)}), 201


@bp.post("/<int:share_id>/revoke")
@auth_required()
def revoke_share(share_id: int):
    share = _share_scope().filter_by(id=share_id).first_or_404()
    share.is_revoked = True
    db.session.commit()
    return jsonify({"ok": True})


@bp.get("/public/<string:token>")
def public_share(token: str):
    share = _public_share(token)
    if not share:
        return jsonify({"error": "Share is unavailable"}), 404
    return jsonify(
        {
            "item": {
                "token": share.token,
                "expiresAt": share.expires_at.isoformat() + "Z" if share.expires_at else None,
                "viewCount": share.view_count,
                "maxViews": share.max_views,
                "burnAfterRead": share.burn_after_read,
                "publicFileUrl": f"/api/shares/public/{share.token}/file",
                "media": serialize_media(share.media),
            }
        }
    )


@bp.get("/public/<string:token>/file")
def public_share_file(token: str):
    share = _public_share(token)
    if not share:
        return jsonify({"error": "Share is unavailable"}), 404
    share.view_count += 1
    share.last_viewed_at = datetime.utcnow()
    if share.burn_after_read:
        share.is_revoked = True
    db.session.commit()
    media = share.media.canonical_root
    return build_streaming_response(
        media.storage_path,
        media.is_encrypted,
        media.mime_type,
    )
