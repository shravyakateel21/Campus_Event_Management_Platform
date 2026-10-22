"""Send e-mail through the SMTP server configured in .env (MAIL_* settings)."""

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


def send_email(to, subject, text):
    """Send a plain-text e-mail. Returns True when the server accepted it.

    If MAIL_SERVER is empty (e-mail switched off) nothing is sent. While the app
    runs in debug mode the message is printed in the terminal instead, so the
    reset code can still be tested on a laptop. Never leave debug on in production.
    """
    cfg = current_app.config
    if not cfg["MAIL_SERVER"]:
        if current_app.debug:
            print("=" * 60)
            print("MAIL_SERVER is not set - e-mail NOT sent. Message would have been:")
            print(f"To: {to}\nSubject: {subject}\n\n{text}")
            print("=" * 60)
        else:
            current_app.logger.error("MAIL_SERVER is not set; could not e-mail %s", to)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to
    msg.set_content(text)

    try:
        context = ssl.create_default_context()
        if cfg["MAIL_PORT"] == 465:
            server = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15, context=context)
        else:
            server = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15)
        with server:
            if cfg["MAIL_PORT"] != 465 and cfg["MAIL_USE_TLS"]:
                server.starttls(context=context)
            if cfg["MAIL_USERNAME"]:
                server.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            server.send_message(msg)
        return True
    except Exception as exc:  # network, login or TLS problem
        current_app.logger.error("Could not send e-mail to %s: %s", to, exc)
        return False