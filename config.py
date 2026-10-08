"""Configuration for the Campus Event Management Platform.

Values are read from environment variables (see .env.example) so that the
same code runs on a laptop and on a college server without edits.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # MySQL
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = _int("DB_PORT", 3306)
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "NewPassword123")
    DB_NAME = os.getenv("DB_NAME", "campus_events")
    DB_POOL_SIZE = _int("DB_POOL_SIZE", 5)

    # Attendance rules
    # How long before the start time the attendance page opens, and how long
    # after the end time it stays open (both in minutes).
    ATTENDANCE_OPENS_BEFORE_MIN = _int("ATTENDANCE_OPENS_BEFORE_MIN", 30)
    ATTENDANCE_CLOSES_AFTER_MIN = _int("ATTENDANCE_CLOSES_AFTER_MIN", 30)

    # Number of reverse proxies in front of Flask. 0 when Flask is reached
    # directly (the usual college-LAN setup). Only raise this if you run
    # behind Nginx, otherwise a student can fake their IP with a header.
    TRUSTED_PROXY_COUNT = _int("TRUSTED_PROXY_COUNT", 0)

    # Certificates
    COLLEGE_NAME = os.getenv("COLLEGE_NAME", "A J Institute of Engineering & Technology")
    CERTIFICATE_SIGNATORY = os.getenv("CERTIFICATE_SIGNATORY", "Head of Department")

    # Created automatically on first run if no admin account exists yet.
    # Change the password after logging in, or set these in .env before first run.
    DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@college.edu")
    DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    DEFAULT_ADMIN_NAME = os.getenv("DEFAULT_ADMIN_NAME", "Admin")