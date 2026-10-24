"""Login, student self-registration and logout."""

import hashlib
import re
import secrets
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import mailer
import security

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _safe_next(value):
    """Return `value` only if it is a path on this site.

    Used for the "log in, then continue to ..." links. Anything else (for example
    //evil.com, /\\evil.com or https://evil.com) is ignored, so a crafted login link
    cannot send someone to another website after they sign in.
    """
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


_EVENT_PAGE = re.compile(r"^/student/events/(\d+)/?$")


def _event_for_next(next_url):
    """If the visitor is heading to an event page, return that event.

    Lets the login and sign-up pages show what they are registering for.
    Only approved events and only public columns are returned.
    """
    match = _EVENT_PAGE.match(next_url or "")
    if not match:
        return None
    return db.query_one(
        "SELECT id, title, category, venue, start_datetime FROM events "
        "WHERE id = %s AND status = 'approved'", (int(match.group(1)),))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

    next_url = _safe_next(request.args.get("next"))
    event_ctx = _event_for_next(next_url)

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.query_one("SELECT * FROM users WHERE email = %s", (email,))
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
            return render_template("login.html", email=email, next_url=next_url, event=event_ctx)
        if not user["is_active"]:
            flash("This account has been deactivated. Contact the administrator.", "error")
            return render_template("login.html", email=email, next_url=next_url, event=event_ctx)

        security.login_user(user)
        db.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))
        if next_url:
            return redirect(next_url)
        return redirect(url_for(security.HOME_FOR_ROLE[user["role"]]))

    return render_template("login.html", email="", next_url=next_url, event=event_ctx)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Students create their own account. Organizers are added by the admin."""
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

    next_url = _safe_next(request.args.get("next"))
    event_ctx = _event_for_next(next_url)
    form = {"name": "", "email": "", "department": "", "phone": ""}

    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        form["email"] = form["email"].lower()
        # (removed: form["usn"] = form["usn"].upper())
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if len(form["name"]) < 3:
            errors.append("Enter your full name.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Enter a valid email address.")
        problem = security.password_error(password)
        if problem:
            errors.append(problem)
        if password != confirm:
            errors.append("The two passwords do not match.")
        if db.query_one("SELECT id FROM users WHERE email = %s", (form["email"],)):
            errors.append("An account already exists with this email.")
        if form["usn"] and db.query_one("SELECT id FROM users WHERE usn = %s", (form["usn"],)):
            errors.append("An account already exists with this USN.")

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("register.html", form=form, next_url=next_url, event=event_ctx)

        db.execute(
                "INSERT INTO users (name, email, password_hash, role, department, phone) "
                "VALUES (%s, %s, %s, 'student', %s, %s)",
                (form["name"], form["email"], generate_password_hash(password),
                 form["department"] or None, form["phone"] or None),
            )
        flash("Account created. Log in to continue.", "success")
        return redirect(url_for("auth.login", next=next_url))

    return render_template("register.html", form=form, next_url=next_url, event=event_ctx)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))

# ---------------------------------------------------------------- forgot password
# Step 1 (/forgot-password):        the person types their e-mail; a reset LINK is
#                                   e-mailed to that address.
# Step 2 (/reset-password/<token>): the link opens a page where they choose a new password.

def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _site_base():
    """Address put in the e-mailed link (SITE_URL in .env, else the address of the request)."""
    return (current_app.config["SITE_URL"] or request.host_url).rstrip("/")


def _send_reset_link(user, email):
    cfg = current_app.config
    # Do not send another link while the previous one is still fresh.
    recent = db.scalar(
        "SELECT COUNT(*) FROM password_resets WHERE user_id = %s AND used_at IS NULL "
        "AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND)",
        (user["id"], cfg["RESET_RESEND_SECONDS"]))
    if recent:
        return

    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM password_resets WHERE user_id = %s", (user["id"],))
    db.execute(
        "INSERT INTO password_resets (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s MINUTE))",
        (user["id"], _token_hash(token), cfg["RESET_LINK_MINUTES"]))

    link = f"{_site_base()}{url_for('auth.reset_password', token=token)}"
    mailer.send_email(
        email,
        f"Reset your password - {cfg['COLLEGE_NAME']}",
        f"Hello {user['name']},\n\n"
        "We received a request to reset your Campus Events password.\n"
        "Click the link below to choose a new password:\n\n"
        f"{link}\n\n"
        f"This link is valid for {cfg['RESET_LINK_MINUTES']} minutes and can be used once.\n\n"
        "If you did not ask to reset your password, ignore this e-mail - "
        "your password has not been changed.\n\n"
        f"{cfg['COLLEGE_NAME']} - Campus Events")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not EMAIL_RE.match(email):
            flash("Enter a valid email address.", "error")
            return render_template("forgot_password.html", email=email)

        user = db.query_one(
            "SELECT id, name, role, is_active FROM users WHERE email = %s", (email,))
        # Administrator passwords are not reset from the website.
        if user and user["is_active"] and user["role"] != "admin":
            _send_reset_link(user, email)

        flash("If that email is registered, a password reset link has been sent to it. "
              f"The link is valid for {current_app.config['RESET_LINK_MINUTES']} minutes.",
              "success")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html", email=email)


def _user_for_token(token):
    """Return the user a live (unused, unexpired) reset token belongs to, else None."""
    return db.query_one(
        "SELECT u.id, u.role, u.is_active, r.id AS reset_id "
        "FROM password_resets r JOIN users u ON u.id = r.user_id "
        "WHERE r.token_hash = %s AND r.used_at IS NULL AND r.expires_at > NOW() "
        "AND u.is_active = 1 AND u.role <> 'admin'", (_token_hash(token),))


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

    user = _user_for_token(token)
    if user is None:
        flash("This reset link is invalid or has expired. Request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        problem = security.password_error(password)
        if problem:
            flash(problem, "error")
        elif password != confirm:
            flash("The two passwords do not match.", "error")
        else:
            db.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                       (generate_password_hash(password), user["id"]))
            db.execute("UPDATE password_resets SET used_at = NOW() "
                       "WHERE user_id = %s AND used_at IS NULL", (user["id"],))
            flash("Password changed. Log in with your new password.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)