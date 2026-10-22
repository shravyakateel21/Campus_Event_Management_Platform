"""Public pages: anyone can read an event's details before deciding to sign up."""

from datetime import datetime

from flask import Blueprint, abort, g, redirect, render_template, url_for

import db

public_bp = Blueprint("public", __name__)

# Only public columns are selected on purpose: the venue's Wi-Fi settings,
# review notes and similar organizer/admin data never reach this page.
PUBLIC_EVENT_SQL = """
    SELECT e.id, e.title, e.description, e.category, e.venue,
           e.start_datetime, e.end_datetime, e.registration_deadline,
           e.capacity, e.status, u.name AS organizer_name,
           (SELECT COUNT(*) FROM registrations r
             WHERE r.event_id = e.id AND r.status = 'registered') AS registered_count
    FROM events e
    JOIN users u ON u.id = e.organizer_id
    WHERE e.id = %s
"""


@public_bp.route("/events/<int:event_id>")
def event_detail(event_id):
    event = db.query_one(PUBLIC_EVENT_SQL, (event_id,))
    if event is None or event["status"] != "approved":
        abort(404)  # pending, rejected and cancelled events are not public

    # A signed-in student gets the full page, with their own registration status.
    if g.user and g.user["role"] == "student":
        return redirect(url_for("student.event_detail", event_id=event_id))

    now = datetime.now()
    seats_left = max(event["capacity"] - event["registered_count"], 0)

    closed_reason = ""
    if event["end_datetime"] < now:
        closed_reason = "This event has ended."
    elif event["registration_deadline"] < now:
        closed_reason = ("Registration closed on "
                         + event["registration_deadline"].strftime("%d %b %Y, %I:%M %p") + ".")
    elif seats_left == 0:
        closed_reason = "All seats are taken."

    return render_template("event_public.html", event=event, seats_left=seats_left,
                           registration_open=not closed_reason, closed_reason=closed_reason)