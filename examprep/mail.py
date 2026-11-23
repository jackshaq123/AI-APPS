"""Outgoing email. Without SMTP settings, messages are logged (local dev)."""
import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


def send_email(config, to, subject, text):
    if not config.get("SMTP_HOST"):
        log.warning("SMTP not configured; email to %s not sent.\nSubject: %s\n%s", to, subject, text)
        return False
    msg = EmailMessage()
    msg["From"] = config["MAIL_FROM"] or config["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=20) as smtp:
        smtp.starttls()
        if config.get("SMTP_USER"):
            smtp.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
        smtp.send_message(msg)
    return True
