"""
Voice-of-Customer monitor — US+ Health
=======================================
Aggregates the *words* customers write, across every channel that exposes text
through an API, themes them, and escalates clusters that look like a real
product problem rather than ordinary noise.

Sources
-------
  returns   Amazon SP-API FBA customer returns — the `customer-comments` field.
            Genuine free text, written by the buyer at return time.
  messages  Amazon buyer messages, read from Gmail over IMAP.

  reviews   NOT AVAILABLE. Review text sits behind Amazon's sign-in wall: the
            Helium 10 API exposes only review count and a one-decimal rating,
            SP-API has no reviews endpoint, and an unauthenticated fetch of the
            review page is bot-blocked. Star-rating movement is tracked
            separately by review_monitor_js.py. Nothing here can see review
            prose, so returns are the earliest text signal we actually get —
            in practice customers return before they review.

Why themes rather than sentiment
--------------------------------
A star rating tells you someone is unhappy. It does not tell you the bottles
have brown sediment in them. Themes keep the specific complaint intact and let
the same complaint arriving on two SKUs in one week surface as one incident.

Castor oil odour
----------------
Deliberately suppressed: castor oil genuinely smells, complaints are constant,
and the team has judged it a non-issue. Suppression is narrow — a castor
complaint that ALSO reports contamination or a safety symptom still escalates,
because "smells bad AND has particles floating in it" is not the known issue.
"""

import argparse
import collections
import datetime as dt
import email
import imaplib
import json
import os
import re

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

import config  # noqa: E402
from alerts import send_alert, is_dry_run  # noqa: E402
from returns_monitor import fetch_returns  # noqa: E402

DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
STATE_FILE = os.path.join(DATA_DIR, "voc_state.json")

LOOKBACK_DAYS = 7


# ── Themes ─────────────────────────────────────────────────────────────────────
# Ordered by seriousness. Patterns are deliberately loose — recall matters more
# than precision here, since a missed contamination report costs far more than
# an extra line in a digest.

THEMES = {
    "safety": {
        "label": "Safety / reaction",
        "patterns": r"\b(burn(ed|ing|t)?|rash|irritat\w*|blister|sick|ill|nausea|"
                    r"vomit\w*|allerg\w*|reaction|hospital|poison\w*|unsafe|"
                    r"chemical burn|itch\w*|swell\w*)\b",
    },
    "contamination": {
        "label": "Contamination / foreign matter",
        "patterns": r"\b(float\w*|brown (spec|fleck|flake|gunk|stuff|particle)\w*|"
                    r"specks?|flakes?|gunk|sediment|particles?|residue|mold\w*|"
                    r"mould\w*|chunk\w*|debris|cloudy|murky|contaminat\w*|"
                    r"sewage|slime|film|growth|black spot\w*|dirty)\b",
    },
    "odor": {
        "label": "Smell / odour",
        "patterns": r"\b(smell\w*|odou?r\w*|stink\w*|rancid|sour|foul|"
                    r"funky|off-smell|stench|reek\w*)\b",
    },
    "leak": {
        "label": "Leaking / seal failure",
        "patterns": r"\b(leak\w*|spill\w*|seal\w*|cap (was )?(loose|off|broken)|"
                    r"broken seal|not sealed|unsealed|crack\w*|burst|"
                    r"came open|opened in transit)\b",
    },
    "efficacy": {
        "label": "Did not work",
        "patterns": r"\b(did ?n[o']t work|does ?n[o']t work|no (effect|result)|"
                    r"useless|ineffective|waste of money|no difference)\b",
    },
    "not_as_described": {
        "label": "Not as described",
        "patterns": r"\b(not as described|different (from|than)|not what (i|I) "
                    r"(ordered|expected)|misleading|wrong (item|product|size)|"
                    r"mislabel\w*|fake|counterfeit)\b",
    },
    "consistency": {
        # Anchored to explicit product-property complaints. Bare "thick"/"thin"
        # matched delivery chatter, so they need a subject to attach to.
        "label": "Colour / texture / consistency",
        "patterns": r"\b((too|very|really) (thick|thin|watery|runny)|"
                    r"discolou?r\w*|much (darker|lighter)|"
                    r"colou?r (was|is|looks|seems) (off|different|wrong|darker|lighter)|"
                    r"(texture|consistency) (is|was|seems|looks) \w+|"
                    r"separat(ed|ing) (out|into)|congeal\w*)\b",
    },
}

# Themes that constitute a genuine product-integrity problem. A cluster of
# these escalates; the softer themes only ever inform.
CRITICAL_THEMES = {"safety", "contamination"}

# Reasons that already signal a product fault, used to weight returns.
QUALITY_REASONS = {
    "DEFECTIVE", "NOT_AS_DESCRIBED", "QUALITY_UNACCEPTABLE",
    "MISSING_PARTS", "NOT_COMPATIBLE",
}


def _compiled():
    return {k: re.compile(v["patterns"], re.I) for k, v in THEMES.items()}


PATTERNS = _compiled()


# ── Castor-oil odour suppression ───────────────────────────────────────────────

def _is_castor(asin: str, product_name: str = "") -> bool:
    name = config.ASIN_NAMES.get(asin, "") or product_name
    return "castor" in name.lower()


def should_suppress(asin: str, product_name: str, themes: set[str]) -> bool:
    """
    Drop castor-oil odour complaints — a known, accepted characteristic.

    Narrow on purpose: only suppress when odour is the ONLY thing reported. If
    the same comment also mentions contamination or a safety symptom, it is not
    the known issue and must still surface.
    """
    if not themes or not _is_castor(asin, product_name):
        return False
    if themes & CRITICAL_THEMES:
        return False
    return themes <= {"odor"}


# ── Classification ─────────────────────────────────────────────────────────────

def classify(text: str) -> set[str]:
    if not text:
        return set()
    return {name for name, rx in PATTERNS.items() if rx.search(text)}


# Amazon wraps some buyer messages in a Customer Service preamble. Classifying
# that boilerplate produces themes nobody wrote, so cut down to the buyer's own
# words where the marker is present.
_APOS = r"['’ʼ`]?"          # Amazon sends curly apostrophes, not ASCII
BOILERPLATE_CUTS = (
    rf"Here{_APOS}s a description of (the )?(issue|their concern|problem)[:\s\-]*",
    rf"the customer{_APOS}s? (message|comment|question|concern)[:\s\-]*",
    rf"Customer{_APOS}s? comments?[:\s\-]*",
    r"reached out to us with some questions about a purchase they made from you[.:\s\-]*",
)
BOILERPLATE_PREFIX = re.compile(
    r"^\s*Dear Amazon Seller,.*?(This is Amazon.{0,40}Customer Service team\.?)?\s*",
    re.I | re.DOTALL,
)


def _clean(text: str) -> str:
    """Return comments arrive pipe-delimited with HTML entities baked in."""
    text = (text.replace("&#39;", "'").replace("&quot;", '"')
                .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    text = text.replace("|", " · ")
    text = re.sub(r"\s+", " ", text).strip()

    # Prefer whatever follows the "here's the issue" marker — that is the buyer.
    for marker in BOILERPLATE_CUTS:
        match = re.search(marker, text, re.I)
        if match:
            tail = text[match.end():].strip()
            if len(tail) > 15:
                return tail
    return text


# ── Source: returns ────────────────────────────────────────────────────────────

def voc_from_returns(days: int) -> list[dict]:
    items = []
    for row in fetch_returns(days=days):
        comment = _clean(row.get("customer-comments", ""))
        reason  = row.get("reason", "")
        if not comment and reason not in QUALITY_REASONS:
            continue

        asin = row.get("asin", "")
        name = row.get("product-name", "")
        themes = classify(comment)

        # A DEFECTIVE return with no words still counts as a quality signal.
        if not themes and reason in QUALITY_REASONS:
            themes = {"unspecified_defect"}

        items.append({
            "date":    row.get("return-date", "")[:10],
            "source":  "return",
            "asin":    asin,
            "product": config.ASIN_NAMES.get(asin, name[:60]),
            "sku":     row.get("sku", ""),
            "order":   row.get("order-id", ""),
            "reason":  reason,
            "text":    comment,
            "themes":  themes,
            "key":     f"return:{row.get('license-plate-number') or row.get('order-id')}:{reason}",
        })
    return items


# ── Source: buyer messages ─────────────────────────────────────────────────────

MSG_BODY_RE = re.compile(r"-+\s*Message:\s*-+\s*\n(.*?)\n\s*-+\s*End message\s*-+",
                         re.DOTALL)
ASIN_RE = re.compile(r"\b(B0[A-Z0-9]{8})\b")


def voc_from_messages(days: int) -> tuple[list[dict], bool]:
    """Returns (items, source_healthy). Empty-but-healthy differs from broken."""
    address  = os.environ.get("GMAIL_ADDRESS", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not address or not password:
        print("  Buyer messages: Gmail not configured, skipping")
        return [], False

    items = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(address, password)
        mail.select("inbox")
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'(FROM "marketplace.amazon.com" SINCE {since})')

        for eid in data[0].split():
            _, md = mail.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(md[0][1])

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

            match = MSG_BODY_RE.search(body)
            text = _clean(match.group(1) if match else body[:400])
            if not text:
                continue

            subject = str(email.header.make_header(
                email.header.decode_header(msg["Subject"] or "")))
            order = re.search(r"(\d{3}-\d{7}-\d{7})", subject)
            asin_match = ASIN_RE.search(body)
            asin = asin_match.group(1) if asin_match else ""

            try:
                date = email.utils.parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%d")
            except Exception:
                date = ""

            items.append({
                "date":    date,
                "source":  "message",
                "asin":    asin,
                "product": config.ASIN_NAMES.get(asin, ""),
                "sku":     "",
                "order":   order.group(1) if order else "",
                "reason":  subject.split("(Order:")[0].strip().rstrip(":"),
                "text":    text,
                "themes":  classify(text),
                "key":     f"msg:{msg['Message-ID'] or eid.decode()}",
            })
        mail.logout()
    except Exception as e:
        print(f"  Buyer messages: fetch failed — {e}")
        return items, False
    return items, True


# ── Incident detection ─────────────────────────────────────────────────────────

def build_incidents(items: list[dict]) -> list[dict]:
    """
    Group by (product, theme). One complaint is an anecdote; the same complaint
    on the same product from separate customers is an incident, and that is
    what deserves to interrupt someone's day.
    """
    buckets = collections.defaultdict(list)
    for item in items:
        for theme in item["themes"]:
            if theme == "unspecified_defect":
                continue
            buckets[(item["product"] or item["asin"] or "unknown", theme)].append(item)

    incidents = []
    for (product, theme), group in buckets.items():
        distinct_orders = {g["order"] for g in group if g["order"]}
        skus = {g["sku"] for g in group if g["sku"]}
        critical = theme in CRITICAL_THEMES

        if critical:
            severity = "P0" if len(group) >= 2 else "P1"
        elif len(group) >= 3:
            severity = "P1"
        elif len(group) >= 2:
            severity = "P2"
        else:
            continue  # single non-critical mention is noise

        incidents.append({
            "product":  product,
            "theme":    theme,
            "label":    THEMES[theme]["label"],
            "count":    len(group),
            "orders":   len(distinct_orders),
            "skus":     sorted(skus),
            "severity": severity,
            "items":    sorted(group, key=lambda g: g["date"], reverse=True),
        })

    order = {"P0": 0, "P1": 1, "P2": 2}
    incidents.sort(key=lambda i: (order[i["severity"]], -i["count"]))
    return incidents


# ── State ──────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"seen": [], "seeded": False}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    state["seen"] = state["seen"][-5000:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Rendering ──────────────────────────────────────────────────────────────────

SEV_EMOJI = {"P0": "🔴", "P1": "🟠", "P2": "🟡"}


def _build_slack(incidents: list[dict], suppressed: int) -> tuple[str, list]:
    top = incidents[0]
    blocks = [{
        "type": "header",
        "text": {"type": "plain_text",
                 "text": f"🗣️ Customer feedback — {len(incidents)} issue(s)",
                 "emoji": True},
    }]

    for inc in incidents[:8]:
        quotes = ""
        for item in inc["items"][:3]:
            if item["text"]:
                quotes += f"\n> _{item['text'][:200]}_  ({item['source']}, {item['date']})"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": (
                f"{SEV_EMOJI[inc['severity']]} *{inc['label']}* — {inc['product']}\n"
                f"{inc['count']} report(s) across {inc['orders']} order(s)"
                f"{' · SKUs ' + ', '.join(inc['skus']) if inc['skus'] else ''}"
                f"{quotes}"
            )},
        })

    if len(incidents) > 8:
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"…and {len(incidents) - 8} more. See email."}]})

    footer = "Sources: return comments + buyer messages. Review text is not API-accessible."
    if suppressed:
        footer += f" {suppressed} castor-oil odour mention(s) suppressed."
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})

    return f"{len(incidents)} customer-feedback issue(s) — {top['label']} on {top['product']}", blocks


def _build_email(incidents: list[dict], suppressed: int, days: int) -> tuple[str, str]:
    p0 = sum(1 for i in incidents if i["severity"] == "P0")
    subject = (f"{'URGENT: ' if p0 else ''}Customer feedback — "
               f"{len(incidents)} issue(s) across {days}d")

    colours = {"P0": "#c0392b", "P1": "#e67e22", "P2": "#f1c40f"}
    cards = ""
    for inc in incidents:
        accent = colours[inc["severity"]]
        quotes = ""
        for item in inc["items"][:6]:
            if not item["text"]:
                continue
            quotes += (
                f"<div style='margin:8px 0;padding:10px;background:#fafafa;"
                f"border-left:3px solid {accent}'>"
                f"<em>&ldquo;{item['text'][:400]}&rdquo;</em>"
                f"<div style='color:#888;font-size:12px;margin-top:6px'>"
                f"{item['source']} &middot; {item['date']}"
                f"{' &middot; order ' + item['order'] if item['order'] else ''}"
                f"{' &middot; ' + item['reason'] if item['reason'] else ''}</div></div>"
            )
        cards += f"""
        <div style='border:1px solid {accent};border-radius:6px;padding:16px;margin-bottom:18px'>
          <p style='margin:0 0 4px;font-size:16px'>
            <strong style='color:{accent}'>{inc['severity']} &middot; {inc['label']}</strong>
          </p>
          <p style='margin:0 0 8px;font-size:15px'><strong>{inc['product']}</strong></p>
          <p style='margin:0 0 4px;color:#555;font-size:13px'>
            {inc['count']} report(s) &middot; {inc['orders']} distinct order(s)
            {'&middot; SKUs ' + ', '.join(inc['skus']) if inc['skus'] else ''}
          </p>
          {quotes}
        </div>"""

    note = (f"<p style='color:#888;font-size:12px'>{suppressed} castor-oil odour "
            f"mention(s) suppressed as a known characteristic.</p>" if suppressed else "")

    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:760px'>
      <h2 style='color:#c0392b'>Customer feedback — US+ Health</h2>
      <p>Themes found in customer wording over the last {days} days, grouped by
         product. Ordered most urgent first.</p>
      {cards}
      {note}
      <p style='color:#888;font-size:12px;margin-top:20px'>
        Sources: Amazon return comments (SP-API) and buyer messages (Gmail).
        Review text is not reachable by API — it sits behind Amazon's sign-in
        wall — so star-rating movement is tracked separately.<br>
        US+ Health VOC Monitor &middot; {dt.date.today()}
      </p>
    </body></html>"""
    return subject, html


# ── Main ───────────────────────────────────────────────────────────────────────

def _build_digest(incidents, fresh, item_count, days, sources_ok, suppressed):
    """
    The daily all-clear. Sends whether or not anything is wrong, because a
    monitor that only speaks up on bad news is indistinguishable from a monitor
    that has silently died — which is precisely how the buyer-message and review
    alerts stayed broken for months without anyone noticing.
    """
    p0 = sum(1 for i in incidents if i["severity"] == "P0")
    p1 = sum(1 for i in incidents if i["severity"] == "P1")

    if fresh:
        headline = f"{len(fresh)} new issue(s)"
        emoji, colour = ("🔴", "#c0392b") if p0 else ("🟠", "#e67e22")
    elif incidents:
        headline = f"No new issues — {len(incidents)} still open"
        emoji, colour = "🟡", "#f1c40f"
    else:
        headline = "All clear"
        emoji, colour = "🟢", "#27ae60"

    health = " · ".join(
        f"{'✅' if ok else '❌'} {name}" for name, ok in sources_ok.items()
    )

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"{emoji} Daily customer check — {headline}",
                  "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*{item_count}* customer comments scanned over {days} days · "
            f"*{len(incidents)}* open issue(s) ({p0} P0, {p1} P1)"
            f"{f' · {suppressed} castor odour suppressed' if suppressed else ''}"
        )}},
    ]

    for inc in (fresh or incidents)[:6]:
        quote = next((i["text"] for i in inc["items"] if i["text"]), "")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
            f"{SEV_EMOJI[inc['severity']]} *{inc['label']}* — {inc['product']} "
            f"({inc['count']} report(s))"
            + (f"\n> _{quote[:180]}_" if quote else "")
        )}})

    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": f"Sources: {health} · Review text unavailable (Amazon sign-in wall)"}]})

    rows = ""
    for inc in (fresh or incidents):
        quote = next((i["text"] for i in inc["items"] if i["text"]), "")
        rows += (f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee'>"
                 f"<strong>{inc['severity']}</strong></td>"
                 f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{inc['label']}</td>"
                 f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{inc['product']}</td>"
                 f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{inc['count']}</td></tr>"
                 f"<tr><td colspan='4' style='padding:0 10px 10px;color:#555;font-style:italic'>"
                 f"&ldquo;{quote[:300]}&rdquo;</td></tr>" if quote else "")

    table = (f"<table style='border-collapse:collapse;width:100%;font-size:14px'>"
             f"<tr style='background:#f5f5f5'><th align='left' style='padding:6px 10px'>Sev</th>"
             f"<th align='left' style='padding:6px 10px'>Theme</th>"
             f"<th align='left' style='padding:6px 10px'>Product</th>"
             f"<th align='left' style='padding:6px 10px'>Reports</th></tr>{rows}</table>"
             if rows else "<p>Nothing open.</p>")

    subject = f"Daily customer check — {headline}"
    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:760px'>
      <h2 style='color:{colour}'>Daily customer check — {headline}</h2>
      <p>{item_count} customer comments scanned over the last {days} days.
         {len(incidents)} open issue(s): {p0} P0, {p1} P1.</p>
      {table}
      <p style='color:#888;font-size:12px;margin-top:20px'>
        Source health: {health}<br>
        This email sends every day even when nothing is wrong — if it stops
        arriving, the monitor itself has a problem.<br>
        Review text is not reachable by API. US+ Health &middot; {dt.date.today()}
      </p>
    </body></html>"""
    return subject, html, f"Daily customer check — {headline}", blocks


def run(days: int = LOOKBACK_DAYS, report_only: bool = False, digest: bool = False):
    print("=== Voice-of-Customer Monitor ===")
    print(f"  Window: last {days} days")

    # Track per-source reachability so the digest can distinguish "nothing to
    # report" from "this source stopped answering".
    sources_ok = {}
    try:
        returns_items = voc_from_returns(days)
        sources_ok["returns"] = True
    except Exception as e:
        print(f"  Returns source FAILED — {e}")
        returns_items, sources_ok["returns"] = [], False

    message_items, sources_ok["messages"] = voc_from_messages(days)

    items = returns_items + message_items
    print(f"  {len(items)} customer text item(s) collected "
          f"({len(returns_items)} returns, {len(message_items)} messages).")

    suppressed = 0
    kept = []
    for item in items:
        if should_suppress(item["asin"], item["product"], item["themes"]):
            suppressed += 1
            continue
        kept.append(item)
    if suppressed:
        print(f"  {suppressed} castor-oil odour mention(s) suppressed.")

    incidents = build_incidents(kept)
    print(f"  {len(incidents)} incident(s): "
          f"{sum(1 for i in incidents if i['severity']=='P0')} P0, "
          f"{sum(1 for i in incidents if i['severity']=='P1')} P1, "
          f"{sum(1 for i in incidents if i['severity']=='P2')} P2")

    if report_only:
        for inc in incidents:
            print(f"\n{inc['severity']}  {inc['label']} — {inc['product']}  "
                  f"({inc['count']} reports / {inc['orders']} orders)")
            for item in inc["items"][:5]:
                if item["text"]:
                    print(f"     [{item['date']} {item['source']}] {item['text'][:170]}")
        return

    state = load_state()
    seen = set(state.get("seen", []))
    fresh = [i for i in incidents
             if any(item["key"] not in seen for item in i["items"])]
    for item in kept:
        seen.add(item["key"])
    state["seen"] = list(seen)

    if digest:
        # Always sends, including on an all-clear day. That is the point: a
        # daily heartbeat means a monitor that dies stops being invisible.
        subject, html, slack_text, slack_blocks = _build_digest(
            incidents, fresh, len(items), days, sources_ok, suppressed)
        send_alert(subject, html, slack_text, slack_blocks)
        save_state(state)
        return

    if not state.get("seeded"):
        state["seeded"] = True
        save_state(state)
        print(f"  First run — baseline seeded from {len(kept)} item(s). No alert sent.")
        return

    if not fresh:
        save_state(state)
        print("  No new customer feedback since last run.")
        return

    subject, html = _build_email(fresh, suppressed, days)
    slack_text, slack_blocks = _build_slack(fresh, suppressed)
    send_alert(subject, html, slack_text, slack_blocks)
    save_state(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="US+ Health Voice-of-Customer monitor")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--dry-run", action="store_true",
                        help="Render alerts without sending or saving state")
    parser.add_argument("--report", action="store_true",
                        help="Print an analysis to stdout; send nothing")
    parser.add_argument("--digest", action="store_true",
                        help="Daily heartbeat: always send, even on an all-clear day")
    args = parser.parse_args()

    if args.dry_run:
        os.environ["ALERT_DRY_RUN"] = "1"
        save_state = lambda _s: print("  State: DRY RUN — not saved")  # noqa: E731
        print("*** DRY RUN — nothing will be sent or saved ***")

    run(days=args.days, report_only=args.report, digest=args.digest)
