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
    gmail_address  = os.environ.get("GMAIL_ADDRESS", "")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_address or not gmail_password:
        print("  Email: not configured, skipping")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_address
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipients, msg.as_string())
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
