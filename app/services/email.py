"""
Email delivery via Microsoft Graph API.

Uses the OAuth2 client-credentials flow (application permissions) to acquire a
bearer token from Azure AD, then POSTs to the Graph sendMail endpoint.  No MSAL
dependency is needed — the token exchange is a plain HTTPS POST that httpx handles.

Required Azure AD app permissions (application, not delegated):
  Mail.Send
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi.templating import Jinja2Templates

from app.config import settings

log = logging.getLogger("email")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Module-level token cache for one cron process run.
_cached_token: str | None = None
_token_expires_at: datetime = datetime.min.replace(tzinfo=timezone.utc)

_EMAIL_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


def _format_send_date_ct() -> str:
    """Calendar date in US Central when the email is sent (ERCOT reporting context)."""
    d = datetime.now(ZoneInfo("America/Chicago")).date()
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _slot_display_label(slot: str) -> str:
    if slot == "3AM":
        return "3 AM"
    if slot == "11AM":
        return "11 AM"
    return slot


def _logo_url() -> str:
    """Hosted color logo for light header (`/static/senergy-logo.png`)."""
    base = (settings.base_url or "").strip().rstrip("/")
    if base.startswith(("http://", "https://")):
        return f"{base}/static/senergy-logo.png"
    return "https://www.poweredbysenergy.com/senergy-logo.png"


def _render_dashboard_email_html(view_url: str, forecast_interval: str, slot: str) -> str:
    slot_label = _slot_display_label(slot)
    contact_addr = (settings.email_reply_to or settings.email_sender).strip()
    subject = f"Question about ERCOT 4CP ({slot_label}) — {forecast_interval}"
    contact_href = f"mailto:{contact_addr}?subject={quote(subject, safe='')}"

    template = _EMAIL_TEMPLATES.env.get_template("email/dashboard_report.html")
    return template.render(
        logo_url=_logo_url(),
        dashboard_url=view_url,
        date_str=forecast_interval,
        report_version=f"{slot} Report",
        contact_href=contact_href,
    )


async def _get_access_token() -> str:
    """
    Acquire (or return a cached) OAuth2 client-credentials token for Graph API.
    Refreshes automatically 5 minutes before expiry.
    """
    global _cached_token, _token_expires_at

    now = datetime.now(timezone.utc)
    if _cached_token and now < (_token_expires_at - timedelta(minutes=5)):
        return _cached_token

    token_url = (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}/oauth2/v2.0/token"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.azure_client_id,
                "client_secret": settings.azure_client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )

    if resp.status_code != 200:
        log.error("Graph token request failed %s: %s", resp.status_code, resp.text[:400])
        resp.raise_for_status()

    payload = resp.json()
    _cached_token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    _token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    log.info("Acquired Graph API access token (expires in %ds)", expires_in)
    return _cached_token


async def send_dashboard_email(view_url: str, forecast_interval: str, slot: str = "11AM") -> None:
    """
    Send the dashboard link email via Microsoft Graph API.

    TO  → settings.email_primary_to  (visible recipient, e.g. EnergyManagement@…)
    BCC → settings.email_bcc         (comma-separated client list — hidden from each other)
    """
    # Guard: check required config
    missing = [
        name for name, val in [
            ("AZURE_TENANT_ID",   settings.azure_tenant_id),
            ("AZURE_CLIENT_ID",   settings.azure_client_id),
            ("AZURE_CLIENT_SECRET", settings.azure_client_secret),
            ("EMAIL_SENDER",      settings.email_sender),
            ("EMAIL_PRIMARY_TO",  settings.email_primary_to),
        ] if not val
    ]
    if missing:
        log.warning("Email skipped — missing config: %s", ", ".join(missing))
        return

    bcc_addresses = [e.strip() for e in settings.email_bcc.split(",") if e.strip()]
    if not bcc_addresses:
        log.warning("EMAIL_BCC not set — email skipped")
        return

    # Build Graph API message payload (mirrors _build_email_message from the local script)
    message: dict = {
        "message": {
            "subject": f"Daily ERCOT 4CP 7-Day {slot} Report - {_format_send_date_ct()}",
            "body": {
                "contentType": "HTML",
                "content": _render_dashboard_email_html(view_url, forecast_interval, slot),
            },
            "from": {
                "emailAddress": {"address": settings.email_sender}
            },
            "toRecipients": [
                {"emailAddress": {"address": settings.email_primary_to}}
            ],
            "bccRecipients": [
                {"emailAddress": {"address": addr}} for addr in bcc_addresses
            ],
        }
    }

    if settings.email_reply_to:
        message["message"]["replyTo"] = [
            {"emailAddress": {"address": settings.email_reply_to}}
        ]

    token = await _get_access_token()
    send_url = f"{GRAPH_BASE}/users/{settings.email_sender}/sendMail"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            send_url,
            json=message,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code == 202:
        log.info(
            "Graph API: email sent to TO=%s + %d BCC recipients for %s",
            settings.email_primary_to,
            len(bcc_addresses),
            forecast_interval,
        )
    else:
        log.error("Graph API sendMail failed %s: %s", resp.status_code, resp.text[:400])
        resp.raise_for_status()
