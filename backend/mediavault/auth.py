from __future__ import annotations

from functools import wraps

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .models import User


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="mediahub-auth")


def create_auth_token(user: User) -> str:
    return _serializer().dumps({"user_id": user.id, "role": user.role})


def get_current_user():
    return getattr(g, "current_user", None)


def _extract_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.args.get("token")


def verify_auth_token(token: str | None) -> User | None:
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=current_app.config["TOKEN_TTL_SECONDS"])
    except (BadSignature, SignatureExpired):
        return None
    user = User.query.get(payload.get("user_id"))
    if not user or not user.is_active:
        return None
    return user


def auth_required(admin: bool = False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            token = _extract_token()
            user = verify_auth_token(token)
            if not user:
                return jsonify({"error": "Authentication required"}), 401
            if admin and not user.is_admin:
                return jsonify({"error": "Admin access required"}), 403
            g.current_user = user
            return view(*args, **kwargs)

        return wrapped

    return decorator
