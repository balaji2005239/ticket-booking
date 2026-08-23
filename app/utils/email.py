import smtplib
import ssl
from email.message import EmailMessage
from flask import current_app


def send_email(to_email, subject, html_body, attachments=None):
    """
    Send an HTML email via SMTP. attachments: list of (filename, bytes, mime_subtype).
    Fails soft: logs and returns False on error so booking flow is not blocked.
    """
    cfg = current_app.config
    host = cfg.get("SMTP_HOST")
    if not host:
        current_app.logger.warning("SMTP not configured; skipping email to %s", to_email)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg['SMTP_FROM_NAME']} <{cfg['SMTP_FROM_EMAIL']}>"
    msg["To"] = to_email
    msg.set_content("This message requires an HTML-capable email client.")
    msg.add_alternative(html_body, subtype="html")

    for fname, data, subtype in (attachments or []):
        maintype = "image" if subtype in ("png", "jpeg", "jpg", "gif") else "application"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, cfg["SMTP_PORT"], timeout=15) as server:
            server.starttls(context=context)
            if cfg.get("SMTP_USERNAME"):
                server.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
            server.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        current_app.logger.error("Email send failed to %s: %s", to_email, e)
        return False
