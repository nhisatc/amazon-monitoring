import imaplib
import email
import re
import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from alerts import send_alert  # noqa: E402  (must follow load_dotenv)

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0B995SHD9T")
STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "buyer_slack_state.json")
POLL_INTERVAL = 120  # seconds


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed_ids": []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def parse_buyer_message(msg):
    subject = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
    sender = msg["From"]

    order_match = re.search(r"Order[:\s]*(\d{3}-\d{7}-\d{7})", subject)
    order_id = order_match.group(1) if order_match else "Unknown"

    msg_type = subject
    if "(Order:" in subject:
        msg_type = subject.split("(Order:")[0].strip().rstrip(":")

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")

    buyer_msg = ""
    match = re.search(
        r"-+\s*Message:\s*-+\s*\n(.*?)\n\s*-+\s*End message\s*-+",
        body,
        re.DOTALL,
    )
    if match:
        buyer_msg = match.group(1).strip()
    elif body:
        buyer_msg = body[:500]

    return {
        "order_id": order_id,
        "message_type": msg_type,
        "buyer_message": buyer_msg,
        "subject": subject,
    }


def _build_email(parsed):
    subject = f"Buyer message: {parsed['message_type']} (Order {parsed['order_id']})"
    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:700px'>
      <h2 style='color:#2980b9'>New Amazon buyer message</h2>
      <div style='border:1px solid #2980b9;border-radius:6px;padding:16px;background:#f8fbff'>
        <p style='margin:0 0 6px'><strong>Type:</strong> {parsed['message_type']}</p>
        <p style='margin:0 0 12px'><strong>Order ID:</strong> {parsed['order_id']}</p>
        <p style='margin:0;padding:12px;background:#fff;border-left:3px solid #2980b9;
                  white-space:pre-wrap'>{parsed['buyer_message']}</p>
      </div>
      <p style='margin-top:16px'>
        <a href='https://sellercentral.amazon.com/messaging/inbox'>Reply in Seller Central</a>
        &mdash; Amazon expects a response within 24 hours.
      </p>
    </body></html>"""
    return subject, html


def notify(parsed):
    """Send one buyer message to Slack and email. True if either landed."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":package: New Amazon Buyer Message",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Order ID:*\n{parsed['order_id']}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Type:*\n{parsed['message_type']}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Message:*\n{parsed['buyer_message']}",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Please check Seller Central and respond as soon as possible.",
                }
            ],
        },
    ]

    subject, html = _build_email(parsed)
    result = send_alert(
        subject=subject,
        body_html=html,
        slack_text=f"New Amazon Buyer Message - Order {parsed['order_id']}",
        slack_blocks=blocks,
    )

    # Mark as processed if either channel delivered, so a single failing
    # channel does not cause the message to be re-alerted forever.
    delivered = result["slack"] or result["email"]
    if delivered:
        print(f"  Notified: Order {parsed['order_id']}")
    else:
        print(f"  Both channels failed for Order {parsed['order_id']} — will retry next run")
    return delivered


def check_new_messages():
    state = load_state()
    # Keep insertion order so the trim below drops the OLDEST ids, not
    # arbitrary ones — a plain set would make the [-500:] window meaningless.
    processed_ids = state.get("processed_ids", [])
    processed = set(processed_ids)

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d-%b-%Y")
    _, data = mail.search(None, f'(FROM "marketplace.amazon.com" SINCE {since})')
    email_ids = data[0].split()

    new_count = 0
    for eid in email_ids:
        _, msg_data = mail.fetch(eid, "(RFC822 X-GM-MSGID)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        msg_id = msg["Message-ID"] or eid.decode()

        if msg_id in processed:
            continue

        parsed = parse_buyer_message(msg)
        if parsed["buyer_message"]:
            if notify(parsed):
                processed.add(msg_id)
                processed_ids.append(msg_id)
                new_count += 1

    mail.logout()

    state["processed_ids"] = processed_ids[-500:]
    save_state(state)
    return new_count


def run_loop():
    print(f"Amazon Buyer Message → Slack bot started (checking every {POLL_INTERVAL}s)")
    while True:
        try:
            n = check_new_messages()
            if n:
                print(f"{datetime.now():%H:%M:%S} — Posted {n} new message(s)")
        except Exception as e:
            print(f"{datetime.now():%H:%M:%S} — Error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        n = check_new_messages()
        print(f"Done. Posted {n} new message(s).")
    else:
        run_loop()
