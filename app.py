"""Campus Event Management Platform - application entry point.

Run locally with:  python app.py
"""

import os
from datetime import datetime

from flask import Flask, g, redirect, render_template, url_for
from werkzeug.security import generate_password_hash

import db
import departments
import reminders
import security
from blueprints.admin import admin_bp
from blueprints.auth import auth_bp
from blueprints.organizer import organizer_bp
from blueprints.public import public_bp
from blueprints.student import student_bp
from config import Config


def _ensure_default_admin(app):
    """Create the first admin login if the users table has none yet.

    schema.sql cannot do this itself: a password hash has to be computed by
    Werkzeug at runtime, not written as plain SQL. This runs once per process
    start and is a no-op once any admin account exists.
    """
    with app.app_context():
        existing = db.scalar("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if existing:
            return
        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'admin')",
            (app.config["DEFAULT_ADMIN_NAME"], app.config["DEFAULT_ADMIN_EMAIL"],
             generate_password_hash(app.config["DEFAULT_ADMIN_PASSWORD"])),
        )
        print("=" * 60)
        print("First run: created a default admin account.")
        print(f"  email     {app.config['DEFAULT_ADMIN_EMAIL']}")
        print(f"  password  {app.config['DEFAULT_ADMIN_PASSWORD']}")
        print("Log in and change this password, or set DEFAULT_ADMIN_EMAIL /")
        print("DEFAULT_ADMIN_PASSWORD in .env before the first run.")
        print("=" * 60)

def _ensure_password_reset_table(app):
    """Create the table used by 'Forgot password' if it is not there yet."""
    with app.app_context():
        db.execute(
            "CREATE TABLE IF NOT EXISTS password_resets ("
            " id INT AUTO_INCREMENT PRIMARY KEY,"
            " user_id INT NOT NULL,"
            " token_hash CHAR(64) NOT NULL UNIQUE,"
            " expires_at DATETIME NOT NULL,"
            " used_at DATETIME DEFAULT NULL,"
            " attempts TINYINT NOT NULL DEFAULT 0,"
            " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " CONSTRAINT fk_reset_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            ") ENGINE=InnoDB")
        # Tables made by an older version of this project lack the attempts column.
        has_attempts = db.scalar(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() "
            "AND table_name = 'password_resets' AND column_name = 'attempts'")
        if not has_attempts:
            db.execute("ALTER TABLE password_resets ADD COLUMN attempts TINYINT NOT NULL DEFAULT 0")

def _ensure_reminder_column(app):
    """Add registrations.reminder_sent_at (used by event reminders) if it is missing."""
    with app.app_context():
        has_column = db.scalar(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() "
            "AND table_name = 'registrations' AND column_name = 'reminder_sent_at'")
        if not has_column:
            db.execute("ALTER TABLE registrations ADD COLUMN reminder_sent_at DATETIME DEFAULT NULL")


def _home_data():
    """Live numbers and upcoming events for the public landing page."""
    try:
        upcoming = db.query_all(
            "SELECT id, title, category, venue, start_datetime FROM events "
            "WHERE status = 'approved' AND end_datetime >= NOW() "
            "ORDER BY start_datetime LIMIT 4")
        stats = {
            "events": db.scalar("SELECT COUNT(*) FROM events WHERE status = 'approved' AND end_datetime >= NOW()") or 0,
            "students": db.scalar("SELECT COUNT(*) FROM users WHERE role = 'student'") or 0,
            "certificates": db.scalar("SELECT COUNT(*) FROM certificates") or 0,
        }
    except Exception:
        upcoming, stats = [], {"events": 0, "students": 0, "certificates": 0}
    return {"upcoming": upcoming, "stats": stats}

def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    db.init_app(app)
    _ensure_default_admin(app)
    _ensure_password_reset_table(app)
    _ensure_reminder_column(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(organizer_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def _load_user():
        security.load_current_user()

    @app.route("/")
    def index():
        if g.user:
            return redirect(url_for(security.HOME_FOR_ROLE[g.user["role"]]))
        return render_template("home.html", **_home_data())

    @app.template_filter("dt")
    def format_datetime(value, fmt="%d %b %Y, %I:%M %p"):
        if not value:
            return "-"
        return value.strftime(fmt)

    @app.context_processor
    def inject_globals():
        return {"now": datetime.now(), "college_name": app.config["COLLEGE_NAME"],
                "departments": departments.DEPARTMENTS,
                "password_hint": security.PASSWORD_HINT,
                "password_pattern": security.PASSWORD_PATTERN}

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403,
                               message="You do not have access to that page."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404,
                               message="That page does not exist."), 404

    return app


if __name__ == "__main__":
    DEBUG = True  # set to False before deploying
    app = create_app()
    # In debug mode Flask starts two processes; run the reminder job only in the real one.
    if not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        reminders.start_reminder_thread(app)
    # host 0.0.0.0 so phones on the campus Wi-Fi can reach the server
    app.run(host="0.0.0.0", port=5000, debug=DEBUG)