"""Login, student self-registration and logout."""

import re

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import security

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.query_one("SELECT * FROM users WHERE email = %s", (email,))
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
            return render_template("login.html", email=email)
        if not user["is_active"]:
            flash("This account has been deactivated. Contact the administrator.", "error")
            return render_template("login.html", email=email)

        security.login_user(user)
        db.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for(security.HOME_FOR_ROLE[user["role"]]))

    return render_template("login.html", email="")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Students create their own account. Organizers are added by the admin."""
    if g.user:
        return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))

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
        if len(password) < 6:
            errors.append("Use a password of at least 6 characters.")
        if password != confirm:
            errors.append("The two passwords do not match.")
        if db.query_one("SELECT id FROM users WHERE email = %s", (form["email"],)):
            errors.append("An account already exists with this email.")
        if form["usn"] and db.query_one("SELECT id FROM users WHERE usn = %s", (form["usn"],)):
            errors.append("An account already exists with this USN.")

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("register.html", form=form)

        db.execute(
            "INSERT INTO users (name, email, password_hash, role, usn, department, phone) "
            "VALUES (%s, %s, %s, 'student', %s, %s, %s)",
            (form["name"], form["email"], generate_password_hash(password),
             form["usn"] or None, form["department"] or None, form["phone"] or None),
        )
        flash("Account created. Log in to see the events.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("auth.login"))