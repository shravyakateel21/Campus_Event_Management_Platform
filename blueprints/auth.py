"""Login, student self-registration and logout."""

import hashlib
import hmac
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
    form = {"name": "", "email": "", "usn": "", "department": "", "phone": ""}

    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        form["email"] = form["email"].lower()
        form["usn"] = form["usn"].upper()
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
            "INSERT INTO users (name, email, password_hash, role, usn, department, phone) "
            "VALUES (%s, %s, %s, 'student', %s, %s, %s)",
            (form["name"], form["email"], generate_password_hash(password),
             form["usn"] or None, form["department"] or None, form["phone"] or None),
        )
        flash("Account created. Log in to continue.", "success")
        return redirect(url_for("auth.login", next=next_url))

    return render_template("register.html", form=form, next_url=next_url, event=event_ctx)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))

# ---------------------------------------------------------------- forgot password
# Step 1 (/forgot-password): the person types their e-mail and a 6-digit code is
#         e-mailed to that address.
# Step 2 (/reset-password):  they type the code and a new password.
# The code is never shown on the website, so only the owner of the mailbox can
# reset the password. The page also gives the same answer whether or not the
# e-mail is registered, so nobody can use it to find out who has an account.

def _otp_hash(user_id, otp):
    """Only a keyed hash of the code is stored, never the code itself."""
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{user_id}:{otp}".encode(), hashlib.sha256).hexdigest()


def _send_reset_code(user, email):
    cfg = current_app.config
    # Do not send another code while the previous one is still fresh.
    recent = db.scalar(
        "SELECT COUNT(*) FROM password_resets WHERE user_id = %s AND used_at IS NULL "
        "AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND)",
        (user["id"], cfg["RESET_RESEND_SECONDS"]))
    if recent:
        return

    otp = f"{secrets.randbelow(1_000_000):06d}"
    db.execute("DELETE FROM password_resets WHERE user_id = %s", (user["id"],))
    db.execute(
        "INSERT INTO password_resets (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s MINUTE))",
        (user["id"], _otp_hash(user["id"], otp), cfg["RESET_OTP_MINUTES"]))

    mailer.send_email(
        email,
        f"Your password reset code - {cfg['COLLEGE_NAME']}",
        f"Hello {user['name']},\n\n"
        f"Your password reset code is: {otp}\n\n"
        f"It is valid for {cfg['RESET_OTP_MINUTES']} minutes. "
        "Do not share it with anyone.\n\n"
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
            _send_reset_code(user, email)

        session["reset_email"] = email
        flash("If that email is registered, a 6-digit code has been sent to it. "
              f"It is valid for {current_app.config['RESET_OTP_MINUTES']} minutes.", "success")
        return redirect(url_for("auth.reset_password"))

    return render_template("forgot_password.html", email=email)


def _check_reset_code(email, otp):
    """Return the user if `otp` is the live code for `email`, else None."""
    user = db.query_one(
        "SELECT id, role, is_active FROM users WHERE email = %s", (email,))
    if not user or not user["is_active"] or user["role"] == "admin":
        return None
    row = db.query_one(
        "SELECT id, token_hash, attempts FROM password_resets "
        "WHERE user_id = %s AND used_at IS NULL AND expires_at > NOW() "
        "ORDER BY id DESC LIMIT 1", (user["id"],))
    if not row or row["attempts"] >= current_app.config["RESET_MAX_ATTEMPTS"]:
        return None
    if hmac.compare_digest(row["token_hash"], _otp_hash(user["id"], otp)):
        return user
    db.execute("UPDATE password_resets SET attempts = attempts + 1 WHERE id = %s", (row["id"],))
    return None


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

    email = session.get("reset_email", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        otp = re.sub(r"\D", "", request.form.get("otp", ""))
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        problem = security.password_error(password)
        if problem:
            flash(problem, "error")
        elif password != confirm:
            flash("The two passwords do not match.", "error")
        else:
            user = _check_reset_code(email, otp) if len(otp) == 6 else None
            if user is None:
                flash("That code is wrong or has expired. Check your email, "
                      "or request a new code.", "error")
            else:
                db.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                           (generate_password_hash(password), user["id"]))
                db.execute("UPDATE password_resets SET used_at = NOW() "
                           "WHERE user_id = %s AND used_at IS NULL", (user["id"],))
                session.pop("reset_email", None)
                flash("Password changed. Log in with your new password.", "success")
                return redirect(url_for("auth.login"))

    return render_template("reset_password.html", email=email)