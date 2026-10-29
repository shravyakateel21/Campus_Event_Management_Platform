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
    form = {"name": "", "email": "", "department": "", "phone": ""}

    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        form["email"] = form["email"].lower()
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
# Step 1 (/forgot-password): the person types their e-mail; a 6-digit code is e-mailed.
# Step 2 (/verify-otp):      they type the code. A wrong code counts as an attempt.
# Step 3 (/reset-password/<token>): after the right code they choose a new password.
#                            (<token> is a one-time secret created at step 2, not the code.)

def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _otp_hash(user_id, otp):
    """Keyed hash of the code, so the digits can't be read back out of the database."""
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{user_id}:{otp}".encode(), hashlib.sha256).hexdigest()


def _send_reset_otp(user, email):
    """E-mail a fresh 6-digit code. Returns False if one was sent a moment ago."""
    cfg = current_app.config
    # One code per RESET_RESEND_SECONDS. Used-up codes count too, so locking a code
    # out with wrong guesses does not let anyone ask for a new one straight away.
    recent = db.scalar(
        "SELECT COUNT(*) FROM password_resets WHERE user_id = %s "
        "AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND)",
        (user["id"], cfg["RESET_RESEND_SECONDS"]))
    if recent:
        return False

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
        "We received a request to reset your Campus Events password.\n"
        f"Your verification code is:  {otp}\n\n"
        f"This code is valid for {cfg['RESET_OTP_MINUTES']} minutes. "
        "Do not share it with anyone.\n\n"
        "If you did not ask to reset your password, ignore this e-mail - "
        "your password has not been changed.\n\n"
        f"{cfg['COLLEGE_NAME']} - Campus Events")
    return True


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
            _send_reset_otp(user, email)

        # Same answer whether or not the address is registered.
        session["reset_email"] = email
        flash("If that email is registered, a 6-digit code has been sent to it. "
              f"The code is valid for {current_app.config['RESET_OTP_MINUTES']} minutes.",
              "success")
        return redirect(url_for("auth.verify_otp"))

    return render_template("forgot_password.html", email=email)


@auth_bp.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

    email = session.get("reset_email")
    if not email:
        return redirect(url_for("auth.forgot_password"))

    cfg = current_app.config
    user = db.query_one(
        "SELECT id, name, role, is_active FROM users WHERE email = %s", (email,))
    eligible = bool(user and user["is_active"] and user["role"] != "admin")

    if request.method == "POST":
        # "Send a new code" button
        if request.form.get("action") == "resend":
            if eligible:
                _send_reset_otp(user, email)
            flash("If that email is registered, a new code has been sent. "
                  f"You can ask for another one after {cfg['RESET_RESEND_SECONDS']} seconds.",
                  "success")
            return redirect(url_for("auth.verify_otp"))

        code = request.form.get("otp", "").strip()
        if not re.fullmatch(r"\d{6}", code):
            flash("Enter the 6-digit code from the e-mail.", "error")
            return redirect(url_for("auth.verify_otp"))

        row = None
        if eligible:
            row = db.query_one(
                "SELECT id, token_hash, attempts FROM password_resets "
                "WHERE user_id = %s AND used_at IS NULL AND expires_at > NOW()",
                (user["id"],))

        if row and hmac.compare_digest(row["token_hash"], _otp_hash(user["id"], code)):
            # Right code: swap it for a one-time secret that the next page needs.
            proof = secrets.token_urlsafe(32)
            db.execute(
                "UPDATE password_resets SET token_hash = %s, attempts = 0, "
                "expires_at = DATE_ADD(NOW(), INTERVAL %s MINUTE) WHERE id = %s",
                (_token_hash(proof), cfg["RESET_LINK_MINUTES"], row["id"]))
            session.pop("reset_email", None)
            return redirect(url_for("auth.reset_password", token=proof))

        if row:
            db.execute("UPDATE password_resets SET attempts = attempts + 1 WHERE id = %s",
                       (row["id"],))
            if row["attempts"] + 1 >= cfg["RESET_MAX_ATTEMPTS"]:
                db.execute("UPDATE password_resets SET used_at = NOW() WHERE id = %s",
                           (row["id"],))
                session.pop("reset_email", None)
                flash("Too many wrong attempts. Please request a new code.", "error")
                return redirect(url_for("auth.forgot_password"))

        flash("That code is incorrect or has expired.", "error")
        return redirect(url_for("auth.verify_otp"))

    return render_template("verify_otp.html", email=email, minutes=cfg["RESET_OTP_MINUTES"])


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
        flash("This reset session is invalid or has expired. Please start again.", "error")
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