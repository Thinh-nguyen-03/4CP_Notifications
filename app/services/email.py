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

import httpx

from app.config import settings

log = logging.getLogger("email")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Module-level token cache for one cron process run.
_cached_token: str | None = None
_token_expires_at: datetime = datetime.min.replace(tzinfo=timezone.utc)


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


def _html_body(view_url: str, forecast_interval: str, slot: str) -> str:
    greeting = "Good morning," if slot == "3AM" else "Howdy!"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f5f6f8;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6f8;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:10px;overflow:hidden;
                    box-shadow:0 4px 18px rgba(15,23,42,0.08);">

        <!-- Header -->
        <tr><td style="background:#1a2a4a;padding:28px 36px;">
          <p style="margin:0;font-size:11px;font-weight:700;color:rgba(255,255,255,0.5);
                    letter-spacing:1.2px;text-transform:uppercase;">SENERGY</p>
          <h1 style="margin:8px 0 0;font-size:22px;font-weight:700;color:#f9d27e;line-height:1.2;">
            ERCOT 4CP Forecast Updated
          </h1>
          <p style="margin:6px 0 0;font-size:15px;font-style:italic;color:rgba(255,255,255,0.82);">
            {forecast_interval}
          </p>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:32px 36px 24px;">
          <p style="margin:0 0 16px;font-size:15px;font-family:Calibri,Arial,sans-serif;
                    color:#0f172a;line-height:1.6;">
            {greeting}
          </p>
          <p style="margin:0 0 24px;font-size:15px;font-family:Calibri,Arial,sans-serif;
                    color:#475569;line-height:1.6;">
            The {slot} ERCOT 4CP 7-Day forecast has been refreshed.
            Click below to view the live dashboard — no login required.
          </p>
          <table cellpadding="0" cellspacing="0"><tr><td>
            <a href="{view_url}"
               style="display:inline-block;background:#1a2a4a;color:#ffffff;font-size:15px;
                      font-weight:600;text-decoration:none;padding:14px 32px;border-radius:7px;
                      letter-spacing:0.2px;">
              View Dashboard &rarr;
            </a>
          </td></tr></table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 36px 28px;border-top:1px solid #e4e6ea;">
          <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
            This link is personal and expires in
            <strong>{settings.token_ttl_hours}&nbsp;hours</strong>.
            Please do not forward it. Thank you!
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


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
            "subject": f"Daily ERCOT 4CP 7-Day {slot} Report — {forecast_interval}",
            "body": {
                "contentType": "HTML",
                "content": _html_body(view_url, forecast_interval, slot),
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
