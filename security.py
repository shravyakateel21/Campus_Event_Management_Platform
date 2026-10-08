"""Session handling and role-based access control."""

from functools import wraps

from flask import flash, g, redirect, request, session, url_for

import db

import re

ROLES = ("student", "organizer", "admin")

HOME_FOR_ROLE = {
    "student": "student.dashboard",
    "organizer": "organizer.dashboard",
    "admin": "admin.dashboard",
}


def load_current_user():
    """Attach the logged-in user to `g` before every request."""
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = db.query_one(
            "SELECT id, name, email, role, usn, department, is_active "
            "FROM users WHERE id = %s",
            (user_id,),
        )
        # A user deactivated by the admin loses access immediately.
        if g.user and not g.user["is_active"]:
            session.clear()
            g.user = None


def login_user(user):
    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def role_required(*allowed_roles):
    """Restrict a view to one or more roles."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in allowed_roles:
                flash("That page is not available for your account.", "error")
                return redirect(url_for(HOME_FOR_ROLE[g.user["role"]]))
            return view(*args, **kwargs)

        return wrapped

    return decorator

# ---------- password rules ----------
PASSWORD_HINT = "At least 8 characters, with a capital letter, a digit and a special character (e.g. @ # $ %)."
PASSWORD_PATTERN = r"(?=.*[A-Z])(?=.*[0-9])(?=.*[^A-Za-z0-9\s]).{8,}"


def password_problems(password):
    """Return what is missing from a password; an empty list means it is strong enough."""
    missing = []
    if len(password) < 8:
        missing.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        missing.append("a capital letter")
    if not re.search(r"[0-9]", password):
        missing.append("a digit")
    if not re.search(r"[^A-Za-z0-9\s]", password):
        missing.append("a special character")
    return missing


def password_error(password):
    """One ready-to-flash sentence, or None when the password is fine."""
    missing = password_problems(password)
    return ("Password needs " + ", ".join(missing) + ".") if missing else None