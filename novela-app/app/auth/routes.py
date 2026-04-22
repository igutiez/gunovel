"""Rutas de autenticación."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .logs import log_acceso
from .models import actualizar_ultimo_login, verificar_credenciales


bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.app_view"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = request.remote_addr or "?"
        usuario = verificar_credenciales(username, password)
        if usuario is None:
            log_acceso("LOGIN_FAIL", username or "unknown", ip)
            flash("Credenciales inválidas.", "error")
            return render_template("login.html"), 401
        login_user(usuario, remember=False)
        actualizar_ultimo_login(usuario.username)
        log_acceso("LOGIN_OK", usuario.username, ip)
        return redirect(url_for("main.app_view"))

    return render_template("login.html")


@bp.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    usuario = current_user.username
    ip = request.remote_addr or "?"
    logout_user()
    log_acceso("LOGOUT", usuario, ip)
    return redirect(url_for("auth.login"))
