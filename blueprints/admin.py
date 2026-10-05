"""Administrator module: approve events, manage users, view platform reports."""

import re

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)
from werkzeug.security import generate_password_hash

import db
from security import ROLES, role_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@admin_bp.route("/")
@role_required("admin")
def dashboard():
    stats = {
        "students": db.scalar("SELECT COUNT(*) FROM users WHERE role = 'student'"),
        "organizers": db.scalar("SELECT COUNT(*) FROM users WHERE role = 'organizer'"),
        "events": db.scalar("SELECT COUNT(*) FROM events"),
        "pending": db.scalar("SELECT COUNT(*) FROM events WHERE status = 'pending'"),
        "registrations": db.scalar("SELECT COUNT(*) FROM registrations WHERE status = 'registered'"),
        "attendance": db.scalar("SELECT COUNT(*) FROM attendance"),
        "certificates": db.scalar("SELECT COUNT(*) FROM certificates"),
    }
    pending = db.query_all(
        "SELECT e.*, u.name AS organizer_name FROM events e JOIN users u ON u.id = e.organizer_id"
        " WHERE e.status = 'pending' ORDER BY e.start_datetime")
    upcoming = db.query_all(
        "SELECT e.*, u.name AS organizer_name,"
        " (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.id AND r.status='registered') AS registered_count"
        " FROM events e JOIN users u ON u.id = e.organizer_id"
        " WHERE e.status = 'approved' AND e.end_datetime >= NOW()"
        " ORDER BY e.start_datetime LIMIT 8")
    return render_template("admin/dashboard.html", stats=stats, pending=pending,
                           upcoming=upcoming)


@admin_bp.route("/events")
@role_required("admin")
def events():
    status = request.args.get("status", "").strip()
    sql = ("SELECT e.*, u.name AS organizer_name,"
           " (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.id AND r.status='registered') AS registered_count,"
           " (SELECT COUNT(*) FROM attendance a WHERE a.event_id = e.id) AS attended_count"
           " FROM events e JOIN users u ON u.id = e.organizer_id")
    params = ()
    if status in ("pending", "approved", "rejected", "cancelled"):
        sql += " WHERE e.status = %s"
        params = (status,)
    sql += " ORDER BY e.start_datetime DESC"
    return render_template("admin/events.html", events=db.query_all(sql, params),
                           status=status)


@admin_bp.route("/events/<int:event_id>/review", methods=["POST"])
@role_required("admin")
def review_event(event_id):
    decision = request.form.get("decision")
    note = request.form.get("review_note", "").strip()[:255] or None
    if decision not in ("approved", "rejected", "cancelled"):
        flash("Choose approve or reject.", "error")
        return redirect(url_for("admin.events"))

    event = db.query_one("SELECT title FROM events WHERE id = %s", (event_id,))
    if event is None:
        flash("That event no longer exists.", "error")
        return redirect(url_for("admin.events"))

    db.execute("UPDATE events SET status = %s, review_note = %s WHERE id = %s",
               (decision, note, event_id))
    wording = {"approved": "approved and visible to students",
               "rejected": "rejected", "cancelled": "cancelled"}[decision]
    flash(f"'{event['title']}' is {wording}.", "success")
    return redirect(request.referrer or url_for("admin.events"))


@admin_bp.route("/users")
@role_required("admin")
def users():
    """Students who have actually signed in. Organizers/admins are managed
    through 'Add organizer or admin' rather than listed on this page."""
    keyword = request.args.get("q", "").strip()
    sql = "SELECT * FROM users WHERE role = 'student' AND last_login IS NOT NULL"
    params = []
    if keyword:
        sql += " AND (name LIKE %s OR email LIKE %s)"
        params += [f"%{keyword}%"] * 2
    sql += " ORDER BY last_login DESC"
    return render_template("admin/users.html", users=db.query_all(sql, tuple(params)),
                           keyword=keyword)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@role_required("admin")
def create_user():
    """Used to add organizers and other administrators."""
    form = {"name": "", "email": "", "role": "organizer", "department": "", "phone": ""}

    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        form["email"] = form["email"].lower()
        password = request.form.get("password", "")

        errors = []
        if len(form["name"]) < 3:
            errors.append("Enter the full name.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Enter a valid email address.")
        if form["role"] not in ROLES:
            errors.append("Choose a role.")
        if len(password) < 6:
            errors.append("Set a password of at least 6 characters.")
        if db.query_one("SELECT id FROM users WHERE email = %s", (form["email"],)):
            errors.append("An account already exists with this email.")

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("admin/user_form.html", form=form)

        db.execute(
            "INSERT INTO users (name, email, password_hash, role, department, phone) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (form["name"], form["email"], generate_password_hash(password), form["role"],
             form["department"] or None, form["phone"] or None))
        flash(f"{form['name']} can now log in as {form['role']}.", "success")
        return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", form=form)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_user(user_id):
    if user_id == g.user["id"]:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))

    user = db.query_one("SELECT name, is_active FROM users WHERE id = %s", (user_id,))
    if user is None:
        flash("That account no longer exists.", "error")
        return redirect(url_for("admin.users"))

    new_state = 0 if user["is_active"] else 1
    db.execute("UPDATE users SET is_active = %s WHERE id = %s", (new_state, user_id))
    flash(f"{user['name']} is now {'active' if new_state else 'deactivated'}.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/reports")
@role_required("admin")
def reports():
    per_event = db.query_all(
        "SELECT e.id, e.title, e.category, e.start_datetime, e.status, u.name AS organizer_name,"
        " (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.id AND r.status='registered') AS registered_count,"
        " (SELECT COUNT(*) FROM attendance a WHERE a.event_id = e.id) AS attended_count,"
        " (SELECT ROUND(AVG(f.rating),2) FROM feedback f WHERE f.event_id = e.id) AS avg_rating,"
        " (SELECT COUNT(*) FROM certificates c WHERE c.event_id = e.id) AS certificate_count"
        " FROM events e JOIN users u ON u.id = e.organizer_id"
        " WHERE e.status IN ('approved','cancelled') ORDER BY e.start_datetime DESC")
    for row in per_event:
        row["turnout"] = (round(row["attended_count"] * 100 / row["registered_count"])
                          if row["registered_count"] else 0)

    by_category = db.query_all(
        "SELECT e.category, COUNT(*) AS event_count,"
        " (SELECT COUNT(*) FROM registrations r JOIN events e2 ON e2.id = r.event_id"
        "   WHERE e2.category = e.category AND r.status='registered') AS registrations"
        " FROM events e WHERE e.status = 'approved' GROUP BY e.category ORDER BY registrations DESC")

    top_students = db.query_all(
        "SELECT u.name, u.usn, COUNT(a.id) AS events_attended"
        " FROM attendance a JOIN users u ON u.id = a.student_id"
        " GROUP BY u.id, u.name, u.usn ORDER BY events_attended DESC, u.name LIMIT 10")

    return render_template("admin/reports.html", per_event=per_event,
                           by_category=by_category, top_students=top_students)