"""
Transactional email via Brevo's HTTP API — not raw SMTP.

This was originally smtplib against Brevo's SMTP relay (matching the
brief's "no extra email SDK" architecture decision), but Render blocks
outbound SMTP traffic entirely: confirmed by testing valid SMTP credentials
that authenticate successfully from an unrestricted network, then time out
on every port (587, 465, 2525) when the exact same code runs on Render.
Brevo's HTTP API is a plain HTTPS POST on port 443 — immune to that class of
problem, since it's the same kind of request this app already makes
successfully elsewhere (e.g. every browser fetch() call). Uses bare
`requests`, not a Brevo vendor SDK, to keep the "no extra email SDK" spirit
(minimal, replaceable dependency) even though the payload shape below is
Brevo-specific — swapping providers later means changing this file's
request body, not swapping out a whole SDK.

Requires BREVO_API_KEY (Brevo dashboard -> SMTP & API -> API Keys — a
different credential from an SMTP key/login, despite similar naming).
Fails soft: any error is logged and returns False rather than raising, so a
booking/waitlist flow is never broken by an email problem.
"""
import base64

import requests
from flask import current_app

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(to_email, subject, html_body, attachments=None):
    """
    Send an HTML email via Brevo's REST API.
    attachments: list of (filename, bytes, mime_subtype) — mime_subtype is
    accepted for interface compatibility (the previous smtplib version used
    it to pick a MIME maintype) but unused here; Brevo infers content type
    from the filename extension.
    """
    cfg = current_app.config
    api_key = cfg.get("BREVO_API_KEY")
    if not api_key:
        current_app.logger.warning("BREVO_API_KEY not configured; skipping email to %s", to_email)
        return False

    payload = {
        "sender": {"name": cfg["EMAIL_FROM_NAME"], "email": cfg["EMAIL_FROM_ADDRESS"]},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
    }
    if attachments:
        payload["attachment"] = [
            {"name": fname, "content": base64.b64encode(data).decode("ascii")}
            for fname, data, _subtype in attachments
        ]

    try:
        resp = requests.post(
            BREVO_API_URL,
            headers={"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
            json=payload,
            timeout=15,
        )
        if resp.status_code >= 300:
            current_app.logger.error("Email send failed to %s: HTTP %s %s", to_email, resp.status_code, resp.text)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        current_app.logger.error("Email send failed to %s: %s", to_email, e)
        return False
