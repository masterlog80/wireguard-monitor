"""User management blueprint (create, change password, delete)."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from config import Config
from .auth import get_user_store

users_bp = Blueprint("users", __name__, url_prefix="/users")


def _min_password_length() -> int:
    return current_app.config.get("MIN_PASSWORD_LENGTH", Config.MIN_PASSWORD_LENGTH)


@users_bp.route("/")
@login_required
def list_users():
    """Display the Users management page."""
    store = get_user_store()
    usernames = store.list_users()
    return render_template(
        "users.html", usernames=usernames, min_password_length=_min_password_length()
    )


@users_bp.route("/create", methods=["POST"])
@login_required
def create_user():
    """Handle the Create User form submission."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if not username:
        flash("Username is required.", "danger")
    elif not password:
        flash("Password is required.", "danger")
    elif len(password) < _min_password_length():
        flash(f"Password must be at least {_min_password_length()} characters.", "danger")
    elif password != confirm:
        flash("Passwords do not match.", "danger")
    else:
        store = get_user_store()
        if store.create_user(username, password):
            flash(f"User '{username}' created successfully.", "success")
        else:
            flash(f"User '{username}' already exists.", "warning")

    return redirect(url_for("users.list_users"))


@users_bp.route("/<username>/change-password", methods=["POST"])
@login_required
def change_password(username: str):
    """Handle the Change Password form submission for *username*."""
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not new_password:
        flash("New password is required.", "danger")
    elif len(new_password) < _min_password_length():
        flash(f"Password must be at least {_min_password_length()} characters.", "danger")
    elif new_password != confirm:
        flash("Passwords do not match.", "danger")
    else:
        store = get_user_store()
        if store.change_password(username, new_password):
            flash(f"Password for '{username}' updated successfully.", "success")
        else:
            flash(f"User '{username}' not found.", "danger")

    return redirect(url_for("users.list_users"))


@users_bp.route("/<username>/delete", methods=["POST"])
@login_required
def delete_user(username: str):
    """Delete *username* (cannot delete the currently logged-in user)."""
    if username == current_user.username:
        flash("You cannot delete your own account while logged in.", "danger")
        return redirect(url_for("users.list_users"))

    store = get_user_store()
    if store.delete_user(username):
        flash(f"User '{username}' deleted.", "success")
    else:
        flash(f"User '{username}' not found.", "danger")

    return redirect(url_for("users.list_users"))
