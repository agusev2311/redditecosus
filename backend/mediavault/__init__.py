from __future__ import annotations

from flask import Flask, jsonify, redirect, request
from flask_cors import CORS

from .config import Config
from .extensions import db
from .services.jobs import start_background_services
from .services.settings import seed_default_settings
from .services.storage import ensure_storage_tree


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,
    )

    from .routes.admin import bp as admin_bp
    from .routes.auth import bp as auth_bp
    from .routes.media import bp as media_bp
    from .routes.setup import bp as setup_bp
    from .routes.shares import bp as shares_bp
    from .routes.tags import bp as tags_bp
    from .routes.uploads import bp as uploads_bp
    from .routes.users import bp as users_bp

    app.register_blueprint(setup_bp, url_prefix="/api/setup")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(tags_bp, url_prefix="/api/tags")
    app.register_blueprint(uploads_bp, url_prefix="/api/uploads")
    app.register_blueprint(media_bp, url_prefix="/api/media")
    app.register_blueprint(shares_bp, url_prefix="/api/shares")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    def _guess_frontend_url() -> str:
        configured = app.config["FRONTEND_BASE_URL"].strip()
        if configured and "localhost" not in configured and "127.0.0.1" not in configured:
            return configured.rstrip("/")
        host = request.host.split(":", 1)[0]
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        return f"{scheme}://{host}:8080"

    @app.get("/")
    def index():
        return redirect(_guess_frontend_url(), code=302)

    @app.get("/api")
    def api_index():
        return jsonify(
            {
                "status": "ok",
                "message": "MediaHub backend is running.",
                "frontendUrl": _guess_frontend_url(),
                "healthUrl": "/api/health",
            }
        )

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    with app.app_context():
        ensure_storage_tree()
        db.create_all()
        seed_default_settings(app)
        start_background_services(app)

    return app
