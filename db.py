"""Thin MySQL access layer built on a connection pool.

Every query in the application goes through one of the four helpers below, so
connection handling and cursor cleanup live in exactly one place.
"""

import mysql.connector
from mysql.connector import pooling
from flask import current_app, g

_pool = None


def init_app(app):
    """Create the pool once at start-up and close connections per request."""
    global _pool
    _pool = pooling.MySQLConnectionPool(
        pool_name="campus_events_pool",
        pool_size=app.config["DB_POOL_SIZE"],
        host=app.config["DB_HOST"],
        port=app.config["DB_PORT"],
        user=app.config["DB_USER"],
        password=app.config["DB_PASSWORD"],
        database=app.config["DB_NAME"],
        autocommit=False,
        charset="utf8mb4",
    )
    app.teardown_appcontext(_close_connection)


def get_connection():
    """One pooled connection per request, reused by every query in it."""
    if "db_conn" not in g:
        g.db_conn = _pool.get_connection()
    return g.db_conn


def _close_connection(exception=None):
    conn = g.pop("db_conn", None)
    if conn is None:
        return
    try:
        if exception:
            conn.rollback()
    finally:
        conn.close()  # returns it to the pool


def query_all(sql, params=()):
    """Return every matching row as a list of dicts."""
    cur = get_connection().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def query_one(sql, params=()):
    """Return the first matching row as a dict, or None."""
    cur = get_connection().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def execute(sql, params=()):
    """Run an INSERT/UPDATE/DELETE and commit. Returns the new row id."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    except mysql.connector.Error:
        conn.rollback()
        raise
    finally:
        cur.close()


def scalar(sql, params=()):
    """Run a COUNT/SUM style query and return the single value."""
    cur = get_connection().cursor()
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close()