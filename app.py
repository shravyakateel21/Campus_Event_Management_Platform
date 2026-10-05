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
        return redirect(url_for("auth.login"))

    @app.template_filter("dt")
    def format_datetime(value, fmt="%d %b %Y, %I:%M %p"):
        if not value:
            return "-"
        return value.strftime(fmt)

    @app.context_processor
    def inject_globals():
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