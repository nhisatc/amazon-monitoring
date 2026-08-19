"""
Return-reason monitor — Amazon SP-API
--------------------------------------
Pulls the FBA Customer Returns report and alerts on returns that signal a
product problem, including the buyer's own comment where they left one.

Amazon's returns report is not a live feed — rows land within a few hours of
the return being scanned — so this runs a few times a day rather than
continuously. That is the floor Amazon imposes, not a limitation of this script.

Reasons are graded:
  QUALITY  — product is wrong or faulty. Alerted, highest priority.
  DAMAGE   — arrived damaged. Alerted, secondary (FC/carrier fault, not the product).
  OTHER    — buyer changed their mind, wrong item ordered, undeliverable.
             Counted in the summary line but not alerted individually.

First run seeds the baseline without alerting, so you do not get a wall of
historical returns.
"""

import datetime as dt
import gzip
import hashlib
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from alerts import send_alert  # noqa: E402

ENDPOINT       = "https://sellingpartnerapi-na.amazon.com"
MARKETPLACE_ID = os.environ.get("MARKETPLACE_ID", "ATVPDKIKX0DER")
DATA_DIR       = os.path.join(os.path.dirname(__file__), "data")
STATE_FILE     = os.path.join(DATA_DIR, "returns_state.json")

# How far back to pull each run. Wider than the run interval so late-arriving
# rows are not missed; dedup by key stops repeat alerts.
LOOKBACK_DAYS = 7

QUALITY_REASONS = {
    "DEFECTIVE",
    "NOT_AS_DESCRIBED",
    "QUALITY_UNACCEPTABLE",
    "MISSING_PARTS",
    "NOT_COMPATIBLE",
    "APPAREL_STYLE",
}

DAMAGE_REASONS = {
    "DAMAGED_BY_FC",
    "DAMAGED_BY_CARRIER",
}

REASON_LABELS = {
    "DEFECTIVE":            "Defective",
    "NOT_AS_DESCRIBED":     "Not as described",
    "QUALITY_UNACCEPTABLE": "Quality unacceptable",
    "MISSING_PARTS":        "Missing parts",
    "NOT_COMPATIBLE":       "Not compatible",
    "DAMAGED_BY_FC":        "Damaged at fulfillment center",
    "DAMAGED_BY_CARRIER":   "Damaged by carrier",
}


# ── SP-API ─────────────────────────────────────────────────────────────────────

def get_access_token() -> str:
    resp = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": os.environ["SP_API_REFRESH_TOKEN"],
            "client_id":     os.environ["LWA_APP_ID"],
            "client_secret": os.environ["LWA_CLIENT_SECRET"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _decode(raw: bytes) -> str:
    """
    Amazon serves this report as cp1252, not UTF-8 — buyer comments routinely
    contain curly apostrophes (0x92) that are invalid UTF-8. Decoding as UTF-8
    with errors='replace' silently corrupts them ("don't" -> "don?t"), so try
    UTF-8 first and fall back to cp1252 rather than mangling the text.
    """
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_returns(days: int = LOOKBACK_DAYS) -> list[dict]:
    """Request, poll for, and download the FBA customer returns report."""
    headers = {
        "x-amz-access-token": get_access_token(),
        "Content-Type":       "application/json",
    }
    end   = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=days)

    create = requests.post(
        f"{ENDPOINT}/reports/2021-06-30/reports",
        headers=headers,
        json={
            "reportType":     "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA",
            "marketplaceIds": [MARKETPLACE_ID],
            "dataStartTime":  start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dataEndTime":    end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        timeout=30,
    )
    create.raise_for_status()
    report_id = create.json()["reportId"]
    print(f"  Report {report_id} requested ({days}d window)…")

    document_id = None
    for _ in range(40):
        time.sleep(6)
        status = requests.get(
            f"{ENDPOINT}/reports/2021-06-30/reports/{report_id}",
            headers=headers,
            timeout=30,
        ).json()
        state = status.get("processingStatus")
        if state == "DONE":
            document_id = status["reportDocumentId"]
            break
        if state in ("CANCELLED", "FATAL"):
            raise RuntimeError(f"Report {report_id} ended as {state}")
    if not document_id:
        raise RuntimeError(f"Report {report_id} did not finish in time")

    doc = requests.get(
        f"{ENDPOINT}/reports/2021-06-30/documents/{document_id}",
        headers=headers,
        timeout=30,
    ).json()

    raw = requests.get(doc["url"], timeout=60).content
    if doc.get("compressionAlgorithm") == "GZIP":
        raw = gzip.decompress(raw)

    lines = _decode(raw).splitlines()
    if not lines:
        return []

    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) < len(header):
            fields += [""] * (len(header) - len(fields))
        rows.append(dict(zip(header, fields)))
    return rows


# ── State ──────────────────────────────────────────────────────────────────────

def return_key(row: dict) -> str:
    """
    Stable per-unit identity. License plate is unique per returned unit but is
    blank on undeliverable returns, so fall back to a hash of the row's
    identifying fields.
    """
    lpn = row.get("license-plate-number", "").strip()
    if lpn:
        return lpn
    basis = "|".join(
        row.get(f, "") for f in ("return-date", "order-id", "sku", "reason")
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"seen": [], "seeded": False}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    # Keep the window bounded; well above the volume of any lookback period.
    state["seen"] = state["seen"][-5000:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Formatting ─────────────────────────────────────────────────────────────────

def _grade(reason: str) -> str:
    if reason in QUALITY_REASONS:
        return "quality"
    if reason in DAMAGE_REASONS:
        return "damage"
    return "other"


def _label(reason: str) -> str:
    return REASON_LABELS.get(reason, reason.replace("_", " ").title())


def _build_email(quality: list[dict], damage: list[dict], other_count: int) -> tuple[str, str]:
    total = len(quality) + len(damage)
    subject = f"Return alert: {total} product-issue return(s) — US+ Health"

    def card(row, accent):
        comment = row.get("customer-comments", "").strip()
        comment_html = (
            f"<p style='margin:8px 0 0;padding:10px;background:#f5f5f5;"
            f"border-left:3px solid {accent};font-style:italic'>"
            f"&ldquo;{comment}&rdquo;</p>"
            if comment
            else "<p style='margin:8px 0 0;color:#999;font-size:12px'>"
                 "No comment left by the buyer.</p>"
        )
        return f"""
        <div style='border:1px solid {accent};border-radius:6px;padding:16px;
                    margin-bottom:16px;background:#fffafa'>
          <p style='margin:0 0 6px;font-size:15px'>
            <strong style='color:{accent}'>{_label(row.get('reason', ''))}</strong>
            &nbsp;&middot;&nbsp; {row.get('return-date', '')[:10]}
          </p>
          <p style='margin:0 0 6px;font-size:14px'>
            {row.get('product-name', '')[:110]}
          </p>
          <p style='margin:0;font-size:13px;color:#555'>
            <strong>ASIN:</strong>
            <a href='https://www.amazon.com/dp/{row.get("asin", "")}'>{row.get('asin', '')}</a>
            &nbsp;|&nbsp; <strong>SKU:</strong> {row.get('sku', '')}
            &nbsp;|&nbsp; <strong>Order:</strong> {row.get('order-id', '')}
          </p>
          {comment_html}
        </div>"""

    body = ""
    if quality:
        body += "<h3 style='color:#c0392b;margin-top:20px'>Product issues</h3>"
        body += "".join(card(r, "#c0392b") for r in quality)
    if damage:
        body += "<h3 style='color:#e67e22;margin-top:20px'>Damaged in transit / at FC</h3>"
        body += "".join(card(r, "#e67e22") for r in damage)

    footer = (
        f"<p style='color:#888;font-size:12px;margin-top:20px'>"
        f"{other_count} other new return(s) in this window "
        f"(changed mind, wrong item ordered, undeliverable) — not itemised.</p>"
        if other_count
        else ""
    )

    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:700px'>
      <h2 style='color:#c0392b'>Return alert — US+ Health</h2>
      <p>{total} new return(s) came back for reasons that point at the product itself.</p>
      {body}
      {footer}
      <p style='color:#888;font-size:12px;margin-top:24px'>
        Automated via Amazon SP-API &middot; US+ Health Monitor &middot; {dt.date.today()}
      </p>
    </body></html>"""
    return subject, html


def _build_slack(quality: list[dict], damage: list[dict], other_count: int) -> tuple[str, list]:
    total = len(quality) + len(damage)
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"↩️ {total} product-issue return(s)", "emoji": True},
        }
    ]

    for row in (quality + damage)[:12]:
        comment = row.get("customer-comments", "").strip()
        icon = "🔴" if _grade(row.get("reason", "")) == "quality" else "🟠"
        text = (
            f"{icon} *{_label(row.get('reason', ''))}* — {row.get('return-date', '')[:10]}\n"
            f"{row.get('product-name', '')[:90]}\n"
            f"`{row.get('asin', '')}` · SKU `{row.get('sku', '')}` · Order `{row.get('order-id', '')}`"
        )
        if comment:
            text += f"\n> _{comment[:280]}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    if total > 12:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"…and {total - 12} more. See the email for the full list."}],
        })

    if other_count:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"{other_count} other new return(s) (changed mind / wrong item / undeliverable) — not itemised.",
            }],
        })

    return f"{total} product-issue return(s) — US+ Health", blocks


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    print("=== Returns Monitor (SP-API) ===")
    state = load_state()
    seen  = set(state.get("seen", []))

    rows = fetch_returns()
    print(f"  {len(rows)} return row(s) in the last {LOOKBACK_DAYS} days.")

    new_rows = []
    for row in rows:
        key = return_key(row)
        if key in seen:
            continue
        seen.add(key)
        new_rows.append(row)

    state["seen"] = list(seen)

    if not state.get("seeded"):
        state["seeded"] = True
        save_state(state)
        print(f"  First run — baseline seeded with {len(new_rows)} existing return(s). No alert sent.")
        return

    if not new_rows:
        save_state(state)
        print("  No new returns.")
        return

    quality = [r for r in new_rows if _grade(r.get("reason", "")) == "quality"]
    damage  = [r for r in new_rows if _grade(r.get("reason", "")) == "damage"]
    other   = len(new_rows) - len(quality) - len(damage)

    print(f"  New: {len(quality)} quality, {len(damage)} damage, {other} other.")

    if not quality and not damage:
        save_state(state)
        print("  Nothing alert-worthy — state updated only.")
        return

    quality.sort(key=lambda r: r.get("return-date", ""), reverse=True)
    damage.sort(key=lambda r: r.get("return-date", ""), reverse=True)

    subject, html = _build_email(quality, damage, other)
    slack_text, slack_blocks = _build_slack(quality, damage, other)
    send_alert(subject, html, slack_text, slack_blocks)

    save_state(state)


if __name__ == "__main__":
    run()
