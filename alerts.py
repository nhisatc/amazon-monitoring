"""
Shared alert delivery — Slack and email.

Every monitor in this repo sends through here so alerts land in both places
with consistent formatting. Slack is the fast path (phone notification);
email is the durable record.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

FALLBACK_RECIPIENTS = (
    "carrie@usplushealth.com,max@usplushealth.com,"
    "julian@usplushealth.com,hedda@usplushealth.com"
)

# Read config at call time, not import time. Callers load .env themselves, and
# capturing os.environ at import would silently blank the Slack token whenever
# this module happened to be imported before load_dotenv() ran.


def _recipients() -> list[str]:
    raw = os.environ.get("ALERT_RECIPIENTS") or FALLBACK_RECIPIENTS
    return [r.strip() for r in raw.split(",") if r.strip()]


def _sender() -> tuple[str, str]:
    """
    The account alerts are sent FROM.

    Deliberately separate from GMAIL_ADDRESS, which is the mailbox the buyer
    message monitor logs into to READ Amazon's messages. Those two are not the
    same account: Amazon delivers to the Gmail address, but alerts should come
    from the company address. Overloading one variable for both would point the
    reader at an empty mailbox.

    Falls back to the reading account when no separate sender is configured, so
    existing setups keep working unchanged.
    """
    address  = os.environ.get("SMTP_FROM_ADDRESS")  or os.environ.get("GMAIL_ADDRESS", "")
    password = os.environ.get("SMTP_FROM_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD", "")
    return address, password


def is_dry_run() -> bool:
    return os.environ.get("ALERT_DRY_RUN", "").strip().lower() in ("1", "true", "yes")


def post_slack(text: str, blocks: list | None = None) -> bool:
    """Post to the team channel. Returns True on success."""
    token   = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_CHANNEL_ID", "")
    if not token or not channel:
        print("  Slack: not configured (missing token or channel), skipping")
        return False

    payload = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks

    if is_dry_run():
        print(f"  Slack: DRY RUN — would post to {channel}: {text}")
        for block in (blocks or []):
            if block.get("type") == "section":
                body = block.get("text", {}).get("text", "")
                if body:
                    print("          | " + body.replace("\n", "\n          | "))
        return True

    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=payload,
            timeout=30,
        )
        data = resp.json()
    except Exception as e:
        print(f"  Slack: request failed — {e}")
        return False

    if not data.get("ok"):
        print(f"  Slack error: {data.get('error')}")
        return False

    print("  Slack: posted")
    return True


def send_email(subject: str, body_html: str, recipients: list[str] | None = None) -> bool:
    """Send the HTML alert email. Returns True on success."""
    recipients = recipients or _recipients()
    from_address, from_password = _sender()
    if not from_address or not from_password:
        print("  Email: not configured, skipping")
        return False

    if is_dry_run():
        print(f"  Email: DRY RUN — would send '{subject}'")
        print(f"          from {from_address} to {', '.join(recipients)}")
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_address
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_address, from_password)
            server.sendmail(from_address, recipients, msg.as_string())
    except Exception as e:
        print(f"  Email: send failed — {e}")
        return False

    print(f"  Email: sent to {len(recipients)} recipient(s)")
    return True


def send_alert(
    subject: str,
    body_html: str,
    slack_text: str,
    slack_blocks: list | None = None,
    recipients: list[str] | None = None,
) -> dict:
    """
    Deliver one alert to both channels.

    Each channel is attempted independently so a Slack outage never
    suppresses the email, and vice versa.
    """
    return {
        "slack": post_slack(slack_text, slack_blocks),
        "email": send_email(subject, body_html, recipients),
    }
