"""Campus Event Management Platform - application entry point.

Run locally with:  python app.py
"""

from datetime import datetime

from flask import Flask, g, redirect, render_template, url_for
from werkzeug.security import generate_password_hash

import db
import security
from blueprints.admin import admin_bp
from blueprints.auth import auth_bp
from blueprints.organizer import organizer_bp
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

def _home_data():
    """Live numbers and upcoming events for the public landing page."""
    try:
        upcoming = db.query_all(
            "SELECT title, category, venue, start_datetime FROM events "
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

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(organizer_bp)
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
        # Views that compare dates pass their own `now`; this is the fallback.
        return {"now": datetime.now(), "college_name": app.config["COLLEGE_NAME"]}

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
    # host 0.0.0.0 so phones on the campus Wi-Fi can reach the server
    create_app().run(host="0.0.0.0", port=5000, debug=True)