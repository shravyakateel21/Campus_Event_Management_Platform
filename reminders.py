"""Event reminders: e-mail every registered student shortly before an event starts.

How it works
  * A background thread wakes up every REMINDER_CHECK_MINUTES minutes.
  * It finds approved events that start within the next REMINDER_HOURS_BEFORE hours.
  * Each registered student gets one e-mail with the event details.
  * registrations.reminder_sent_at remembers who was already reminded, so nobody
    receives the same reminder twice.

Needs the MAIL_* settings in .env. Without MAIL_SERVER the reminders are off.

You can also run one check by hand (or from Windows Task Scheduler):
    python reminders.py
"""

import threading
import time
from datetime import datetime, timedelta

import db
from mailer import send_email


def _claim(reg_id):
    """Mark one reminder as taken. True only for the caller that wins, so no one gets two."""
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE registrations SET reminder_sent_at = NOW() "
                    "WHERE id = %s AND reminder_sent_at IS NULL", (reg_id,))
        conn.commit()
        return cur.rowcount == 1
    finally:
        cur.close()


def _release(reg_id):
    """Put a reminder back in the queue after a failed send, so it is tried again."""
    db.execute("UPDATE registrations SET reminder_sent_at = NULL WHERE id = %s", (reg_id,))


def _message(app, row, now):
    cfg = app.config
    start = row["start_datetime"]
    minutes = max(1, int((start - now).total_seconds() // 60))
    if minutes < 60:
        when = f"in about {minutes} minute{'s' if minutes != 1 else ''}"
    else:
        hours = round(minutes / 60)
        when = f"in about {hours} hour{'s' if hours != 1 else ''}"

    opens = start - timedelta(minutes=cfg["ATTENDANCE_OPENS_BEFORE_MIN"])
    lines = [
        f"Hi {row['name']},",
        "",
        f"This is a reminder that \"{row['title']}\" starts {when}.",
        "",
        f"Date and time : {start.strftime('%A, %d %B %Y at %I:%M %p')}",
        f"Venue         : {row['venue']}",
    ]
    if row.get("wifi_ssid"):
        lines.append(f"Wi-Fi network : {row['wifi_ssid']}")
    lines += [
        "",
        f"Connect to the Wi-Fi network above and tap \"Mark me present\" at the venue."
           if row.get("wifi_ssid") else "Tap \"Mark me present\" when you reach the venue.",
    ]
    lines += ["", "See you there!", cfg["COLLEGE_NAME"]]
    return f"Reminder: {row['title']} starts {when}", "\n".join(lines)

def send_due_reminders(app):
    """E-mail every reminder that is due right now. Returns how many were sent."""
    cfg = app.config
    if not cfg["MAIL_SERVER"]:
        return 0
    now = datetime.now()
    cutoff = now + timedelta(hours=cfg["REMINDER_HOURS_BEFORE"])
    sent = 0
    with app.app_context():
        rows = db.query_all(
            "SELECT r.id AS reg_id, u.name, u.email,"
            "       e.id, e.title, e.venue, e.start_datetime, e.wifi_ssid"
            "  FROM registrations r"
            "  JOIN events e ON e.id = r.event_id"
            "  JOIN users  u ON u.id = r.student_id"
            " WHERE r.status = 'registered' AND r.reminder_sent_at IS NULL"
            "   AND e.status = 'approved' AND u.is_active = 1"
            "   AND e.start_datetime > %s AND e.start_datetime <= %s"
            " ORDER BY e.start_datetime", (now, cutoff))
        for row in rows:
            if not _claim(row["reg_id"]):
                continue                      # another process already took it
            subject, text = _message(app, row, now)
            if send_email(row["email"], subject, text):
                sent += 1
            else:
                _release(row["reg_id"])       # try again at the next check
                break                         # mail server trouble: stop this round
    return sent


def start_reminder_thread(app):
    """Start the background job that checks for due reminders."""
    if not app.config["MAIL_SERVER"]:
        print("Event reminders are OFF: set MAIL_SERVER (and the other MAIL_* values) in .env.")
        return
    interval = max(1, app.config["REMINDER_CHECK_MINUTES"]) * 60

    def loop():
        time.sleep(20)                        # let the app finish starting up
        while True:
            try:
                count = send_due_reminders(app)
                if count:
                    print(f"Event reminders: {count} e-mail(s) sent.")
            except Exception as exc:          # never let the thread die
                app.logger.error("Event reminder job failed: %s", exc)
            time.sleep(interval)

    threading.Thread(target=loop, name="event-reminders", daemon=True).start()
    print(f"Event reminders are ON: students are e-mailed about "
          f"{app.config['REMINDER_HOURS_BEFORE']} hour(s) before an event.")


if __name__ == "__main__":
    from app import create_app
    print(f"{send_due_reminders(create_app())} reminder(s) sent.")