"""Factory de la aplicación Flask."""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from flask import Flask, redirect, url_for
from flask_login import LoginManager, current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config, ensure_dirs


login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Inicia sesión para continuar."


def _configurar_logging(app: Flask) -> None:
    Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    app_log = Config.LOG_DIR / "app.log"
    handler = TimedRotatingFileHandler(app_log, when="D", backupCount=7, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    )
    handler.setLevel(Config.LOG_LEVEL)
    app.logger.addHandler(handler)
    app.logger.setLevel(Config.LOG_LEVEL)


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder="../static",
        template_folder="../templates",
    )
    app.config.from_object(Config)

    ensure_dirs(Config)
    _configurar_logging(app)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    login_manager.init_app(app)

    from .auth.models import cargar_usuario_por_id

    @login_manager.user_loader
    def _user_loader(user_id: str):  # noqa: D401
        return cargar_usuario_por_id(user_id)

    from .auth.routes import bp as auth_bp
    from .files.routes import bp as files_bp
    from .versioning.routes import bp as versioning_bp
    from .audit.routes import bp as audit_bp
    from .ai.routes import bp as ai_bp
    from .autonomo.routes import bp as autonomo_bp
    from .main.routes import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(versioning_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(autonomo_bp)
    app.register_blueprint(main_bp)

    @app.route("/")
    def _root():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return redirect(url_for("main.app_view"))

    return app
