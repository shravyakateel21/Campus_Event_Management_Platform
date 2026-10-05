"""Session handling and role-based access control."""

from functools import wraps

from flask import flash, g, redirect, request, session, url_for

import db

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