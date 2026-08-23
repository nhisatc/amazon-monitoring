import imaplib
import email
import re
import hashlib
import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from alerts import post_slack  # noqa: E402  (must follow load_dotenv)

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


def notify(parsed):
    """
    Post one buyer message to Slack. Slack only, by design — these run every
    5 minutes and would flood inboxes. Returns and review alerts still go to
    both channels. (An HTML email body for these lived here until 2026-08-20;
    recover it from git history if that changes.)
    """
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

    delivered = post_slack(
        text=f"New Amazon Buyer Message - Order {parsed['order_id']}",
        blocks=blocks,
    )

    # Only mark processed once Slack has actually accepted it. Slack is now the
    # sole channel, so a failure here means nobody saw the message — retry on
    # the next run rather than losing it.
    if delivered:
        print(f"  Notified: Order {parsed['order_id']}")
    else:
        print(f"  Slack delivery failed for Order {parsed['order_id']} — will retry next run")
    return delivered


def content_fingerprint(parsed):
    """
    Identify a buyer message by what it SAYS, not which email carried it.

    Amazon re-sends the same buyer message as separate emails with different
    Message-IDs — order 111-6982615-2011414 arrived twice, 26 minutes apart,
    identical text — so a Message-ID key alerted once per copy. Hashing the
    order plus the normalised message body collapses those duplicates while
    still letting a genuine follow-up (different words) through.
    """
    body = re.sub(r"\s+", " ", (parsed.get("buyer_message") or "")).strip().lower()
    basis = f"{parsed.get('order_id', '')}|{body}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def check_new_messages():
    state = load_state()
    # Keep insertion order so the trim below drops the OLDEST ids, not
    # arbitrary ones — a plain set would make the [-500:] window meaningless.
    processed_ids = state.get("processed_ids", [])
    processed = set(processed_ids)
    fingerprints = state.get("fingerprints", [])
    seen_content = set(fingerprints)

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
            fingerprint = content_fingerprint(parsed)
            if fingerprint in seen_content:
                # Amazon resent a message we have already alerted on. Record the
                # id so we stop re-examining it, but stay quiet.
                print(f"  Duplicate of an already-alerted message "
                      f"(order {parsed['order_id']}) — not re-posting")
                processed.add(msg_id)
                processed_ids.append(msg_id)
                continue

            if notify(parsed):
                processed.add(msg_id)
                processed_ids.append(msg_id)
                seen_content.add(fingerprint)
                fingerprints.append(fingerprint)
                new_count += 1

    mail.logout()

    state["processed_ids"] = processed_ids[-500:]
    state["fingerprints"]  = fingerprints[-500:]
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
    if "--dry-run" in sys.argv:
        os.environ["ALERT_DRY_RUN"] = "1"
        # Same reasoning as the returns monitor: previewing must not consume
        # the message ids, or the real run would skip them as already-sent.
        save_state = lambda _state: print("  State: DRY RUN — not saved")  # noqa: E731
        print("*** DRY RUN — nothing will be sent or saved ***")
    if "--once" in sys.argv or "--dry-run" in sys.argv:
        n = check_new_messages()
        print(f"Done. Posted {n} new message(s).")
    else:
        run_loop()
