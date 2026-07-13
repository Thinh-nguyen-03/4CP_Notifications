"""
One-off: email the new-features announcement (Forecast History + Outlook
Rewind) to the full client list.

Run once from a Render Shell on the web service (same env vars as production):
    python -m app.jobs.send_announcement

Not wired into any cron schedule — this is a single manual send, not a
recurring job. Re-running it sends the announcement again, so only run it once
with TEST_MODE = False.
"""
import asyncio
import logging
import sys

from app.config import settings
from app.database import async_session_maker, engine
from app.db_init import create_tables
from app.routes.predictions import _get_latest_batch
from app.services.email import send_feature_announcement_email
from app.services.view_token import create_view_token

# ---------------------------------------------------------------------------
# TEST_MODE = True  -> sends ONLY to TEST_RECIPIENT (no CC, no BCC, no client list).
# TEST_MODE = False -> the real send: TO is hardcoded to LIVE_RECIPIENT, CC as
#                       configured (EMAIL_CC), BCC = the full client list.
# Send yourself a test first. Flip TEST_MODE back to False only when you're
# ready for the real send — there's no undo once it goes to the full list.
TEST_MODE = False
TEST_RECIPIENT = "pnguyen@poweredbysenergy.com"
LIVE_RECIPIENT = "pnguyen@poweredbysenergy.com"
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("send_announcement")


async def main() -> int:
    if TEST_MODE:
        log.warning("TEST MODE: sending only to %s -- the client list will NOT be emailed.", TEST_RECIPIENT)
    else:
        log.warning("LIVE SEND: sending to the full client list (TO/CC/BCC as configured).")

    await create_tables()

    async with async_session_maker() as session:
        latest = await _get_latest_batch(session, slot=None)
        if latest is None:
            log.error("No predictions in the database yet — nothing to link the announcement to.")
            return 1
        cp_day, slot = latest

        raw_token = await create_view_token(session, slot, cp_day)
        view_url = f"{settings.base_url.rstrip('/')}/r/{raw_token}"

        try:
            await send_feature_announcement_email(
                view_url,
                to_override=TEST_RECIPIENT if TEST_MODE else LIVE_RECIPIENT,
                suppress_cc_bcc=TEST_MODE,
            )
        except Exception:
            log.exception("Announcement email failed to send")
            await engine.dispose()
            return 1

    log.info("Announcement sent, linking to %s", view_url)
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
