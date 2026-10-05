"""Student module: browse events, register, mark attendance, feedback, certificates."""

from datetime import datetime

import mysql.connector
from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, send_file, url_for)

import certificates as cert
import db
import wifi
from security import role_required

student_bp = Blueprint("student", __name__, url_prefix="/student")

EVENT_WITH_COUNTS = """
    SELECT e.*, u.name AS organizer_name,
           (SELECT COUNT(*) FROM registrations r
             WHERE r.event_id = e.id AND r.status = 'registered') AS registered_count
    FROM events e
    JOIN users u ON u.id = e.organizer_id
"""


def _student_event(event_id):
    """An approved event, plus this student's registration/attendance state."""
    event = db.query_one(EVENT_WITH_COUNTS + " WHERE e.id = %s", (event_id,))
    if event is None or event["status"] != "approved":
        abort(404)
    sid = g.user["id"]
    event["my_registration"] = db.query_one(
        "SELECT * FROM registrations WHERE event_id = %s AND student_id = %s",
        (event_id, sid))
    event["my_attendance"] = db.query_one(
        "SELECT * FROM attendance WHERE event_id = %s AND student_id = %s",
        (event_id, sid))
    event["my_feedback"] = db.query_one(
        "SELECT * FROM feedback WHERE event_id = %s AND student_id = %s",
        (event_id, sid))
    event["my_certificate"] = db.query_one(
        "SELECT * FROM certificates WHERE event_id = %s AND student_id = %s",
        (event_id, sid))
    return event


def _registration_state(event):
    """Why a student can or cannot register right now."""
    now = datetime.now()
    reg = event.get("my_registration")
    if reg and reg["status"] == "registered":
        return False, "You are registered for this event."
    if event["end_datetime"] < now:
        return False, "This event is over."
    if event["registration_deadline"] < now:
        return False, "Registration closed on " + event["registration_deadline"].strftime("%d %b, %I:%M %p") + "."
    if event["registered_count"] >= event["capacity"]:
        return False, "All seats are taken."
    return True, ""


@student_bp.route("/")
@role_required("student")
def dashboard():
    sid = g.user["id"]
    upcoming = db.query_all(
        EVENT_WITH_COUNTS +
        " WHERE e.status = 'approved' AND e.end_datetime >= NOW()"
        " ORDER BY e.start_datetime LIMIT 6", ())
    my_next = db.query_all(
        EVENT_WITH_COUNTS +
        " JOIN registrations r ON r.event_id = e.id AND r.student_id = %s"
        " WHERE r.status = 'registered' AND e.end_datetime >= NOW()"
        " ORDER BY e.start_datetime LIMIT 5", (sid,))
    stats = {
        "registered": db.scalar(
            "SELECT COUNT(*) FROM registrations WHERE student_id = %s AND status = 'registered'", (sid,)),
        "attended": db.scalar("SELECT COUNT(*) FROM attendance WHERE student_id = %s", (sid,)),
        "certificates": db.scalar("SELECT COUNT(*) FROM certificates WHERE student_id = %s", (sid,)),
    }
    return render_template("student/dashboard.html", upcoming=upcoming,
                           my_next=my_next, stats=stats)


@student_bp.route("/events")
@role_required("student")
def events():
    keyword = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    show_past = request.args.get("past") == "1"

    sql = EVENT_WITH_COUNTS + " WHERE e.status = 'approved'"
    params = []
    if not show_past:
        sql += " AND e.end_datetime >= NOW()"
    if keyword:
        sql += " AND (e.title LIKE %s OR e.description LIKE %s OR e.venue LIKE %s)"
        params += [f"%{keyword}%"] * 3
    if category:
        sql += " AND e.category = %s"
        params.append(category)
    sql += " ORDER BY e.start_datetime" + (" DESC" if show_past else "")

    rows = db.query_all(sql, tuple(params))
    my_ids = {r["event_id"] for r in db.query_all(
        "SELECT event_id FROM registrations WHERE student_id = %s AND status = 'registered'",
        (g.user["id"],))}
    for row in rows:
        row["is_registered"] = row["id"] in my_ids

    categories = [r["category"] for r in db.query_all(
        "SELECT DISTINCT category FROM events WHERE status = 'approved' ORDER BY category")]
    return render_template("student/events.html", events=rows, categories=categories,
                           keyword=keyword, category=category, show_past=show_past)


@student_bp.route("/events/<int:event_id>")
@role_required("student")
def event_detail(event_id):
    event = _student_event(event_id)
    can_register, reason = _registration_state(event)
    opens_at, closes_at = wifi.attendance_window(
        event, current_app.config["ATTENDANCE_OPENS_BEFORE_MIN"],
        current_app.config["ATTENDANCE_CLOSES_AFTER_MIN"])
    return render_template("student/event_detail.html", event=event,
                           can_register=can_register, reason=reason,
                           attendance_opens=opens_at, attendance_closes=closes_at,
                           now=datetime.now())


@student_bp.route("/events/<int:event_id>/register", methods=["POST"])
@role_required("student")
def register_for_event(event_id):
    event = _student_event(event_id)
    can_register, reason = _registration_state(event)

    if not can_register:
        flash(reason, "error")
        return redirect(url_for("student.event_detail", event_id=event_id))

    try:
        if event["my_registration"]:  # previously cancelled: reopen the same row
            db.execute(
                "UPDATE registrations SET status = 'registered', registered_at = NOW() "
                "WHERE id = %s", (event["my_registration"]["id"],))
        else:
            db.execute(
                "INSERT INTO registrations (event_id, student_id) VALUES (%s, %s)",
                (event_id, g.user["id"]))
    except mysql.connector.IntegrityError:
        # the unique key caught a double submit
        flash("You are already registered for this event.", "error")
        return redirect(url_for("student.event_detail", event_id=event_id))

    flash("Registered. Bring your phone on the day and join the venue Wi-Fi to mark attendance.",
          "success")
    return redirect(url_for("student.event_detail", event_id=event_id))


@student_bp.route("/events/<int:event_id>/cancel", methods=["POST"])
@role_required("student")
def cancel_registration(event_id):
    event = _student_event(event_id)
    if event["my_attendance"]:
        flash("Attendance is already recorded, so this registration cannot be cancelled.", "error")
    elif event["start_datetime"] < datetime.now():
        flash("The event has started, so registration cannot be cancelled.", "error")
    else:
        db.execute(
            "UPDATE registrations SET status = 'cancelled' "
            "WHERE event_id = %s AND student_id = %s", (event_id, g.user["id"]))
        flash("Registration cancelled.", "success")
    return redirect(url_for("student.event_detail", event_id=event_id))


@student_bp.route("/my-events")
@role_required("student")
def my_events():
    rows = db.query_all(
        EVENT_WITH_COUNTS +
        " JOIN registrations r ON r.event_id = e.id AND r.student_id = %s"
        " WHERE r.status = 'registered' ORDER BY e.start_datetime DESC", (g.user["id"],))
    attended = {r["event_id"] for r in db.query_all(
        "SELECT event_id FROM attendance WHERE student_id = %s", (g.user["id"],))}
    given = {r["event_id"] for r in db.query_all(
        "SELECT event_id FROM feedback WHERE student_id = %s", (g.user["id"],))}
    for row in rows:
        row["attended"] = row["id"] in attended
        row["feedback_given"] = row["id"] in given
    return render_template("student/my_events.html", events=rows, now=datetime.now())


# --------------------------------------------------------------------------
# Wi-Fi attendance
# --------------------------------------------------------------------------

@student_bp.route("/events/<int:event_id>/attendance", methods=["GET", "POST"])
@role_required("student")
def attendance(event_id):
    event = _student_event(event_id)
    now = datetime.now()
    opens_at, closes_at = wifi.attendance_window(
        event, current_app.config["ATTENDANCE_OPENS_BEFORE_MIN"],
        current_app.config["ATTENDANCE_CLOSES_AFTER_MIN"])

    client_ip = wifi.get_client_ip(request, current_app.config["TRUSTED_PROXY_COUNT"])
    verified, method, network_message = wifi.verify_network(event, client_ip)

    # Step 1 of the flowchart: is this student registered for the event?
    registered = bool(event["my_registration"] and
                      event["my_registration"]["status"] == "registered")
    # Step 2: is the attendance page open right now?
    in_window = opens_at <= now <= closes_at

    blockers = []
    if not registered:
        blockers.append("You are not registered for this event.")
    if now < opens_at:
        blockers.append("Attendance opens at " + opens_at.strftime("%d %b, %I:%M %p") + ".")
    elif now > closes_at:
        blockers.append("Attendance closed at " + closes_at.strftime("%d %b, %I:%M %p") + ".")

    if request.method == "POST":
        if event["my_attendance"]:
            flash("Your attendance was already recorded.", "error")
            return redirect(url_for("student.attendance", event_id=event_id))
        if blockers:
            flash(blockers[0], "error")
            return redirect(url_for("student.attendance", event_id=event_id))
        if not verified:
            flash(network_message, "error")
            return redirect(url_for("student.attendance", event_id=event_id))

        ssid_reported = request.form.get("ssid", "").strip()[:64] or None
        try:
            db.execute(
                "INSERT INTO attendance (event_id, student_id, ip_address, method, ssid_reported) "
                "VALUES (%s, %s, %s, %s, %s)",
                (event_id, g.user["id"], client_ip, method, ssid_reported))
        except mysql.connector.IntegrityError:
            flash("Your attendance was already recorded.", "error")
            return redirect(url_for("student.attendance", event_id=event_id))

        flash("Attendance recorded.", "success")
        return redirect(url_for("student.attendance", event_id=event_id))

    return render_template("student/attendance.html", event=event, client_ip=client_ip,
                           verified=verified, network_message=network_message,
                           blockers=blockers, in_window=in_window,
                           opens_at=opens_at, closes_at=closes_at, now=now)


# --------------------------------------------------------------------------
# Feedback
# --------------------------------------------------------------------------

@student_bp.route("/events/<int:event_id>/feedback", methods=["GET", "POST"])
@role_required("student")
def feedback(event_id):
    event = _student_event(event_id)

    if event["end_datetime"] > datetime.now():
        flash("Feedback opens once the event is over.", "error")
        return redirect(url_for("student.event_detail", event_id=event_id))
    if not event["my_attendance"]:
        flash("Feedback is open to students whose attendance was recorded.", "error")
        return redirect(url_for("student.event_detail", event_id=event_id))

    if request.method == "POST":
        try:
            rating = int(request.form.get("rating", 0))
        except ValueError:
            rating = 0
        comments = request.form.get("comments", "").strip()

        if rating < 1 or rating > 5:
            flash("Choose a rating between 1 and 5.", "error")
            return render_template("student/feedback.html", event=event, comments=comments)

        if event["my_feedback"]:
            db.execute("UPDATE feedback SET rating = %s, comments = %s, submitted_at = NOW() "
                       "WHERE id = %s", (rating, comments or None, event["my_feedback"]["id"]))
        else:
            db.execute("INSERT INTO feedback (event_id, student_id, rating, comments) "
                       "VALUES (%s, %s, %s, %s)",
                       (event_id, g.user["id"], rating, comments or None))
        flash("Thanks for the feedback.", "success")
        return redirect(url_for("student.event_detail", event_id=event_id))

    return render_template("student/feedback.html", event=event,
                           comments=(event["my_feedback"] or {}).get("comments", ""))


# --------------------------------------------------------------------------
# Certificates
# --------------------------------------------------------------------------

@student_bp.route("/certificates")
@role_required("student")
def certificate_list():
    rows = db.query_all(
        "SELECT e.id, e.title, e.start_datetime, e.venue, e.end_datetime,"
        "       a.marked_at, c.certificate_code, c.issued_at"
        "  FROM attendance a"
        "  JOIN events e ON e.id = a.event_id"
        "  LEFT JOIN certificates c ON c.event_id = e.id AND c.student_id = a.student_id"
        " WHERE a.student_id = %s ORDER BY e.start_datetime DESC", (g.user["id"],))
    return render_template("student/certificates.html", rows=rows, now=datetime.now())


@student_bp.route("/events/<int:event_id>/certificate")
@role_required("student")
def certificate_download(event_id):
    """Issue the certificate on first download, then serve the same record."""
    event = _student_event(event_id)
    sid = g.user["id"]

    if event["end_datetime"] > datetime.now():
        flash("Certificates are issued after the event ends.", "error")
        return redirect(url_for("student.event_detail", event_id=event_id))
    if not event["my_attendance"]:
        flash("A certificate needs a recorded attendance for this event.", "error")
        return redirect(url_for("student.event_detail", event_id=event_id))

    record = event["my_certificate"]
    if record is None:
        code = cert.new_certificate_code(event_id, sid)
        try:
            db.execute("INSERT INTO certificates (event_id, student_id, certificate_code) "
                       "VALUES (%s, %s, %s)", (event_id, sid, code))
        except mysql.connector.IntegrityError:
            pass  # another tab issued it a moment ago
        record = db.query_one(
            "SELECT * FROM certificates WHERE event_id = %s AND student_id = %s",
            (event_id, sid))

    pdf = cert.build_certificate_pdf(
        student=g.user, event=event, certificate=record,
        college_name=current_app.config["COLLEGE_NAME"],
        signatory=current_app.config["CERTIFICATE_SIGNATORY"])
    filename = f"certificate-{event['title'][:30].replace(' ', '-').lower()}.pdf"
    return send_file(pdf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


@student_bp.route("/profile")
@role_required("student")
def profile():
    return render_template("student/profile.html", user=g.user)