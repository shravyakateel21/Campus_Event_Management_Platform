"""Organizer module: create and run events, monitor registrations and attendance."""

import csv
import io
from datetime import datetime

import mysql.connector
from flask import (Blueprint, Response, abort, flash, g, redirect,
                   render_template, request, url_for)

import db
import wifi
from security import role_required

organizer_bp = Blueprint("organizer", __name__, url_prefix="/organizer")

DATETIME_INPUT = "%Y-%m-%dT%H:%M"


def _parse_dt(raw):
    try:
        return datetime.strptime(raw, DATETIME_INPUT)
    except (TypeError, ValueError):
        return None


def _owned_event(event_id):
    """Admins can open any event; an organizer only their own."""
    event = db.query_one(
        "SELECT e.*, u.name AS organizer_name FROM events e "
        "JOIN users u ON u.id = e.organizer_id WHERE e.id = %s", (event_id,))
    if event is None:
        abort(404)
    if g.user["role"] != "admin" and event["organizer_id"] != g.user["id"]:
        abort(403)
    return event


def _read_event_form():
    """Pull the event form out of the request and validate it."""
    form = {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "category": request.form.get("category", "").strip() or "General",
        "venue": request.form.get("venue", "").strip(),
        "start_datetime": request.form.get("start_datetime", ""),
        "end_datetime": request.form.get("end_datetime", ""),
        "registration_deadline": request.form.get("registration_deadline", ""),
        "capacity": request.form.get("capacity", "").strip(),
        "wifi_ssid": request.form.get("wifi_ssid", "").strip(),
        "wifi_cidr": request.form.get("wifi_cidr", "").strip(),
        "wifi_public_ip": request.form.get("wifi_public_ip", "").strip(),
    }
    errors = []

    if len(form["title"]) < 4:
        errors.append("Give the event a title of at least 4 characters.")
    if not form["venue"]:
        errors.append("Enter the venue.")

    start = _parse_dt(form["start_datetime"])
    end = _parse_dt(form["end_datetime"])
    deadline = _parse_dt(form["registration_deadline"])
    if start is None:
        errors.append("Enter the start date and time.")
    if end is None:
        errors.append("Enter the end date and time.")
    if start and end and end <= start:
        errors.append("The end time must be after the start time.")
    if deadline is None:
        errors.append("Enter the registration deadline.")
    if deadline and start and deadline > start:
        errors.append("The registration deadline must fall on or before the start time.")

    try:
        capacity = int(form["capacity"])
        if capacity < 1:
            raise ValueError
    except ValueError:
        capacity = None
        errors.append("Capacity must be a whole number of 1 or more.")

    invalid_ranges = wifi.validate_cidr_text(form["wifi_cidr"])
    if invalid_ranges:
        errors.append("These network ranges are not valid: " + ", ".join(invalid_ranges))
    if not form["wifi_cidr"] and not form["wifi_public_ip"]:
        errors.append("Add the venue network range, or the campus gateway IP, "
                      "so students can mark attendance.")

    values = None
    if not errors:
        values = (form["title"], form["description"] or None, form["category"], form["venue"],
                  start, end, deadline, capacity,
                  form["wifi_ssid"] or None, form["wifi_cidr"] or None,
                  form["wifi_public_ip"] or None)
    return form, errors, values


@organizer_bp.route("/")
@role_required("organizer", "admin")
def dashboard():
    oid = g.user["id"]
    mine = db.query_all(
        "SELECT e.*, "
        " (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.id AND r.status='registered') AS registered_count,"
        " (SELECT COUNT(*) FROM attendance a WHERE a.event_id = e.id) AS attended_count"
        " FROM events e WHERE e.organizer_id = %s ORDER BY e.start_datetime DESC", (oid,))
    stats = {
        "events": len(mine),
        "pending": sum(1 for e in mine if e["status"] == "pending"),
        "registrations": db.scalar(
            "SELECT COUNT(*) FROM registrations r JOIN events e ON e.id = r.event_id "
            "WHERE e.organizer_id = %s AND r.status = 'registered'", (oid,)) or 0,
        "attendance": db.scalar(
            "SELECT COUNT(*) FROM attendance a JOIN events e ON e.id = a.event_id "
            "WHERE e.organizer_id = %s", (oid,)) or 0,
    }
    return render_template("organizer/dashboard.html", events=mine, stats=stats,
                           now=datetime.now())


@organizer_bp.route("/events/new", methods=["GET", "POST"])
@role_required("organizer", "admin")
def create_event():
    form = {k: "" for k in ("title", "description", "category", "venue", "start_datetime",
                            "end_datetime", "registration_deadline", "capacity",
                            "wifi_ssid", "wifi_cidr", "wifi_public_ip")}
    form["capacity"] = "100"

    if request.method == "POST":
        form, errors, values = _read_event_form()
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("organizer/event_form.html", form=form, event=None)

        event_id = db.execute(
            "INSERT INTO events (title, description, category, venue, start_datetime,"
            " end_datetime, registration_deadline, capacity, wifi_ssid, wifi_cidr,"
            " wifi_public_ip, organizer_id, status)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
            values + (g.user["id"],))
        flash("Event saved and sent to the administrator for approval.", "success")
        return redirect(url_for("organizer.event_detail", event_id=event_id))

    return render_template("organizer/event_form.html", form=form, event=None)


@organizer_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@role_required("organizer", "admin")
def edit_event(event_id):
    event = _owned_event(event_id)

    if request.method == "POST":
        form, errors, values = _read_event_form()
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("organizer/event_form.html", form=form, event=event)

        # An edit to an approved event sends it back for approval, so the
        # admin always sees the details students will be shown.
        new_status = "pending" if event["status"] in ("approved", "rejected") else event["status"]
        db.execute(
            "UPDATE events SET title=%s, description=%s, category=%s, venue=%s,"
            " start_datetime=%s, end_datetime=%s, registration_deadline=%s, capacity=%s,"
            " wifi_ssid=%s, wifi_cidr=%s, wifi_public_ip=%s, status=%s, review_note=NULL"
            " WHERE id=%s", values + (new_status, event_id))
        flash("Event updated." + (" It needs approval again." if new_status == "pending" else ""),
              "success")
        return redirect(url_for("organizer.event_detail", event_id=event_id))

    form = {
        "title": event["title"], "description": event["description"] or "",
        "category": event["category"], "venue": event["venue"],
        "start_datetime": event["start_datetime"].strftime(DATETIME_INPUT),
        "end_datetime": event["end_datetime"].strftime(DATETIME_INPUT),
        "registration_deadline": event["registration_deadline"].strftime(DATETIME_INPUT),
        "capacity": str(event["capacity"]),
        "wifi_ssid": event["wifi_ssid"] or "", "wifi_cidr": event["wifi_cidr"] or "",
        "wifi_public_ip": event["wifi_public_ip"] or "",
    }
    return render_template("organizer/event_form.html", form=form, event=event)


@organizer_bp.route("/events/<int:event_id>")
@role_required("organizer", "admin")
def event_detail(event_id):
    event = _owned_event(event_id)
    participants = db.query_all(
        "SELECT u.id, u.name, u.usn, u.email, u.department, r.registered_at,"
        "       a.marked_at, a.method, a.ip_address,"
        "       f.rating, c.certificate_code"
        "  FROM registrations r"
        "  JOIN users u ON u.id = r.student_id"
        "  LEFT JOIN attendance a ON a.event_id = r.event_id AND a.student_id = r.student_id"
        "  LEFT JOIN feedback f ON f.event_id = r.event_id AND f.student_id = r.student_id"
        "  LEFT JOIN certificates c ON c.event_id = r.event_id AND c.student_id = r.student_id"
        " WHERE r.event_id = %s AND r.status = 'registered'"
        " ORDER BY u.name", (event_id,))
    summary = {
        "registered": len(participants),
        "present": sum(1 for p in participants if p["marked_at"]),
        "feedback": sum(1 for p in participants if p["rating"]),
        "certificates": sum(1 for p in participants if p["certificate_code"]),
    }
    summary["absent"] = summary["registered"] - summary["present"]
    return render_template("organizer/event_detail.html", event=event,
                           participants=participants, summary=summary, now=datetime.now())


@organizer_bp.route("/events/<int:event_id>/attendance/<int:student_id>", methods=["POST"])
@role_required("organizer", "admin")
def mark_attendance_manually(event_id, student_id):
    """Fallback for a student whose phone is out of battery or off the network."""
    event = _owned_event(event_id)
    registered = db.query_one(
        "SELECT id FROM registrations WHERE event_id=%s AND student_id=%s AND status='registered'",
        (event_id, student_id))
    if not registered:
        flash("That student is not registered for this event.", "error")
        return redirect(url_for("organizer.event_detail", event_id=event_id))
    try:
        db.execute(
            "INSERT INTO attendance (event_id, student_id, ip_address, method, marked_by) "
            "VALUES (%s, %s, %s, 'manual', %s)",
            (event_id, student_id, request.remote_addr or "-", g.user["id"]))
        flash("Attendance recorded by hand and marked as manual in the report.", "success")
    except mysql.connector.IntegrityError:
        flash("Attendance is already recorded for that student.", "error")
    return redirect(url_for("organizer.event_detail", event_id=event_id))


@organizer_bp.route("/events/<int:event_id>/report.csv")
@role_required("organizer", "admin")
def attendance_csv(event_id):
    event = _owned_event(event_id)
    rows = db.query_all(
        "SELECT u.name, u.usn, u.email, u.department, r.registered_at,"
        "       a.marked_at, a.method, a.ip_address, f.rating, f.comments, c.certificate_code"
        "  FROM registrations r"
        "  JOIN users u ON u.id = r.student_id"
        "  LEFT JOIN attendance a ON a.event_id = r.event_id AND a.student_id = r.student_id"
        "  LEFT JOIN feedback f ON f.event_id = r.event_id AND f.student_id = r.student_id"
        "  LEFT JOIN certificates c ON c.event_id = r.event_id AND c.student_id = r.student_id"
        " WHERE r.event_id = %s AND r.status = 'registered' ORDER BY u.name", (event_id,))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Name", "USN", "Email", "Department", "Registered on",
                     "Attendance", "Marked at", "Method", "IP address",
                     "Rating", "Comments", "Certificate ID"])
    for row in rows:
        writer.writerow([
            row["name"], row["usn"] or "", row["email"], row["department"] or "",
            row["registered_at"].strftime("%Y-%m-%d %H:%M"),
            "Present" if row["marked_at"] else "Absent",
            row["marked_at"].strftime("%Y-%m-%d %H:%M") if row["marked_at"] else "",
            row["method"] or "", row["ip_address"] or "",
            row["rating"] or "", (row["comments"] or "").replace("\n", " "),
            row["certificate_code"] or "",
        ])

    filename = f"{event['title'][:40].replace(' ', '-').lower()}-report.csv"
    return Response(buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@organizer_bp.route("/events/<int:event_id>/feedback")
@role_required("organizer", "admin")
def event_feedback(event_id):
    event = _owned_event(event_id)
    rows = db.query_all(
        "SELECT f.rating, f.comments, f.submitted_at, u.name, u.usn"
        "  FROM feedback f JOIN users u ON u.id = f.student_id"
        " WHERE f.event_id = %s ORDER BY f.submitted_at DESC", (event_id,))
    average = round(sum(r["rating"] for r in rows) / len(rows), 2) if rows else None
    spread = {star: sum(1 for r in rows if r["rating"] == star) for star in range(5, 0, -1)}
    return render_template("organizer/feedback.html", event=event, rows=rows,
                           average=average, spread=spread, total=len(rows))


@organizer_bp.route("/events/<int:event_id>/cancel", methods=["POST"])
@role_required("organizer", "admin")
def cancel_event(event_id):
    event = _owned_event(event_id)
    db.execute("UPDATE events SET status = 'cancelled' WHERE id = %s", (event_id,))
    flash(f"'{event['title']}' is cancelled and no longer listed for students.", "success")
    return redirect(url_for("organizer.dashboard"))