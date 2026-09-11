import imaplib
import email
import re
import hashlib
import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime, parseaddr
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from alerts import post_slack  # noqa: E402  (must follow load_dotenv)

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0B995SHD9T")
STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "buyer_slack_state.json")
POLL_INTERVAL = 120  # seconds

# How long a buyer-keyed thread stays open. Orderless messages are threaded by
# buyer (see thread_key), and a reply inside an old thread notifies nobody —
# so a buyer who comes back weeks later gets a fresh top-level alert instead.
BUYER_THREAD_DAYS = 7


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed_ids": []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def strip_volatile(text):
    """
    Remove the parts of an email body that change between two deliveries of the
    same buyer message.

    Amazon's "Re:" template has no --- Message: --- delimiters, so the parser
    below falls back to raw body text. That raw text carries a tracking URL and
    the quoted history of the thread, both of which differ per send — which is
    how order 111-6982615-2011414 was posted twice on 2026-08-25 (08:08 and
    17:46) with two different fingerprints. Cutting the quoted tail and the
    URLs leaves just what the buyer actually wrote.

    Deliberately conservative: it strips containers, never words. Two genuinely
    different messages still hash differently, so real follow-ups get through.
    """
    # Cut everything from the first reply marker onward — that is quoted history.
    text = re.split(
        r"\n\s*(?:-{2,}\s*Original Message\s*-{2,}"
        r"|On .{0,120}\bwrote:"
        r"|From:\s|Sent:\s|_{5,}|={5,})",
        text,
        maxsplit=1,
    )[0]
    text = re.sub(r"^\s*>.*$", "", text, flags=re.MULTILINE)   # quoted lines
    text = re.sub(r"https?://\S+", "", text)                   # tracking links
    return re.sub(r"\s+", " ", text).strip()


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
        buyer_msg = strip_volatile(body)[:500]

    # Amazon's customer-service relays ("Order inquiry from Amazon customer
    # Daniel") leave the order number out of the subject and put it in the
    # body. Reading only the subject posted them as "Order ID: Unknown", which
    # cannot be threaded — Daniel's leaking-gallon exchange on 2026-09-03/04
    # arrived as two separate top-level alerts and read as a duplicate.
    if order_id == "Unknown" and body:
        in_body = re.search(r"Order\s*(?:number|ID|#)?[:\s#]*(\d{3}-\d{7}-\d{7})", body, re.I)
        if in_body:
            order_id = in_body.group(1)

    return {
        "order_id": order_id,
        "message_type": msg_type,
        "buyer_message": buyer_msg,
        "subject": subject,
        "buyer": buyer_alias(msg),
    }


def buyer_alias(msg):
    """
    Amazon's anonymised address for the buyer — the part before the "+" in
    y22jb59cw6bmgyg+317f60a2-...@marketplace.amazon.com. The suffix changes
    per message; the prefix stays with the buyer, so it links two messages
    from one person when neither carries an order number.
    """
    addr = parseaddr(msg.get("Reply-To") or msg.get("From") or "")[1].lower()
    local, _, domain = addr.partition("@")
    if "+" not in local or not domain.endswith("marketplace.amazon.com"):
        return ""
    return local.split("+", 1)[0]


def thread_key(parsed):
    """
    The Slack thread a message belongs in, as (key, is_buyer_key).

    The order when there is one. Otherwise the buyer: product questions carry
    no order at all, so the buyer's alias is the only thing tying a follow-up
    to the question it follows.
    """
    order = parsed.get("order_id")
    if order and order != "Unknown":
        return order, False
    if parsed.get("buyer"):
        return f"buyer:{parsed['buyer']}", True
    return None, False


def _thread_is_fresh(ts):
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError):
        return True
    return age < BUYER_THREAD_DAYS * 86400


def notify(parsed, thread_ts=None):
    """
    Post one buyer message to Slack. Slack only, by design — these run every
    5 minutes and would flood inboxes. Returns and review alerts still go to
    both channels. (An HTML email body for these lived here until 2026-08-20;
    recover it from git history if that changes.)

    When thread_ts is given the message is posted as a reply inside that
    thread. A customer conversation is a back-and-forth — order
    111-5359978-8095453 sent three messages in two hours, ending with "Okay
    thank you!" — and each one used to notify the whole channel separately.
    Threading keeps the follow-ups readable in context without re-pinging.
    """
    header = (":speech_balloon: Follow-up from buyer" if thread_ts
              else ":package: New Amazon Buyer Message")
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header,
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
        thread_ts=thread_ts,
    )

    # Only mark processed once Slack has actually accepted it. Slack is now the
    # sole channel, so a failure here means nobody saw the message — retry on
    # the next run rather than losing it.
    if delivered:
        kind = "Threaded follow-up" if thread_ts else "Notified"
        print(f"  {kind}: Order {parsed['order_id']}")
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
    body = strip_volatile(parsed.get("buyer_message") or "").lower()
    basis = f"{parsed.get('order_id', '')}|{body}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def legacy_fingerprint(parsed):
    """
    The pre-2026-08-27 hash, kept only so the state file's existing entries
    still match. Without it, every message already alerted on would hash
    differently under the new rules and post a second time on the next run.
    """
    body = re.sub(r"\s+", " ", (parsed.get("buyer_message") or "")).strip().lower()
    return hashlib.sha1(f"{parsed.get('order_id', '')}|{body}".encode("utf-8")).hexdigest()


def check_new_messages():
    state = load_state()
    # Keep insertion order so the trim below drops the OLDEST ids, not
    # arbitrary ones — a plain set would make the [-500:] window meaningless.
    processed_ids = state.get("processed_ids", [])
    processed = set(processed_ids)
    fingerprints = state.get("fingerprints", [])
    seen_content = set(fingerprints)
    # order id -> Slack ts of the message that opened that conversation
    threads = state.get("threads", {})

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
            if fingerprint in seen_content or legacy_fingerprint(parsed) in seen_content:
                # Amazon resent a message we have already alerted on. Record the
                # id so we stop re-examining it, but stay quiet.
                print(f"  Duplicate of an already-alerted message "
                      f"(order {parsed['order_id']}) — not re-posting")
                processed.add(msg_id)
                processed_ids.append(msg_id)
                continue

            # Everything about one order belongs in one Slack thread. The first
            # message opens it; later ones reply inside it. Orderless messages
            # thread by buyer instead, but only while that thread is recent.
            key, by_buyer = thread_key(parsed)
            parent_ts = threads.get(key) if key else None
            if parent_ts and by_buyer and not _thread_is_fresh(parent_ts):
                parent_ts = None

            result = notify(parsed, thread_ts=parent_ts)
            if result:
                processed.add(msg_id)
                processed_ids.append(msg_id)
                seen_content.add(fingerprint)
                fingerprints.append(fingerprint)
                if not parent_ts and isinstance(result, str):
                    # Register the new thread under the order AND the buyer, so
                    # a follow-up that omits the order number still finds it.
                    if key:
                        threads[key] = result
                    if parsed.get("buyer"):
                        threads[f"buyer:{parsed['buyer']}"] = result
                new_count += 1

    mail.logout()

    state["processed_ids"] = processed_ids[-500:]
    state["fingerprints"]  = fingerprints[-500:]
    # Bound the thread map the same way, keeping the most recently opened.
    state["threads"] = dict(list(threads.items())[-300:])
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
    elif "--local-loop" in sys.argv:
        run_loop()
    else:
        # GitHub Actions is the only poster. A local loop keeps its own copy of
        # the state file, which falls behind the one the workflow commits, so
        # it re-posts everything the workflow has already sent. That is what
        # run_buyer_slack.bat / .vbs did when launched with no arguments —
        # they are left in place, but now stop here instead of duplicating.
        print("Not starting a local polling loop: GitHub Actions posts buyer "
              "messages. Use --once or --dry-run to test, or --local-loop if the "
              "workflow schedule has been switched off.")
        sys.exit(1)
