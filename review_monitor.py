"""
Low-star review monitor
-----------------------
Two data sources, whichever is available:

  1. Seller Feedback (SP-API) — always available, catches buyer ratings on
     the seller account (star ratings + comments left after orders).

  2. GET_PRODUCT_REVIEWS (SP-API) — only available with Brand Registry.
     Catches actual product review ratings and text. Skipped gracefully
     if not enrolled.

To unlock product reviews automatically, enroll in Amazon Brand Registry:
  brandservices.amazon.com

Helium 10 (once account is set up) will also cover this automatically.

Run every 2 hours via Task Scheduler.
"""

import json
import os
import gzip
import csv
import time
import datetime
import certifi
import httpx
from io import StringIO

# Patch httpx.Client to always use certifi's CA bundle on Windows
_orig_httpx_client = httpx.Client
class _CertifiedClient(_orig_httpx_client):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("verify", certifi.where())
        super().__init__(*args, **kwargs)
httpx.Client = _CertifiedClient

from sp_api.api import Reports
from sp_api.base import Marketplaces
from sp_api.base.exceptions import SellingApiRequestThrottledException

import config
from mailer import send_alert

SEEN_FILE = os.path.join(config.DATA_DIR, "seen_review_ids.json")


# ── SP-API helpers ─────────────────────────────────────────────────────────────

def _marketplace():
    for m in Marketplaces:
        if m.value[0] == config.MARKETPLACE_ID:
            return m
    return Marketplaces.US


def _reports_api():
    return Reports(
        credentials=config.SP_API_CREDENTIALS,
        marketplace=_marketplace(),
        verify=config.SSL_VERIFY,
    )


def _create_report_with_retry(reports_api, **kwargs) -> dict:
    for attempt in range(5):
        try:
            return reports_api.create_report(**kwargs)
        except SellingApiRequestThrottledException:
            wait = 60 * (attempt + 1)
            print(f"  Rate limited — waiting {wait}s (retry {attempt+1}/5)…")
            time.sleep(wait)
    raise RuntimeError("Exceeded retry limit due to rate limiting.")


def _download_report(reports_api, report_id: str, retries: int = 2) -> str | None:
    """Poll for report completion and return raw text content.
    CANCELLED usually means no data for the period — treated as empty."""
    for _ in range(30):
        time.sleep(10)
        status = reports_api.get_report(report_id).payload
        if status["processingStatus"] == "DONE":
            break
        if status["processingStatus"] == "CANCELLED":
            print(f"  No data for this period (report cancelled by Amazon — this is normal).")
            return None
        if status["processingStatus"] == "FATAL":
            print(f"  Report {report_id} failed with FATAL status.")
            return None

    if "reportDocumentId" not in status:
        return None

    doc     = reports_api.get_report_document(status["reportDocumentId"])
    payload = doc.payload
    is_gzip = payload.get("compressionAlgorithm", "").upper() == "GZIP"

    resp = httpx.get(payload["url"], verify=certifi.where(), timeout=60)
    resp.raise_for_status()
    raw = resp.content
    if is_gzip:
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


# ── Source 1: Seller Feedback ──────────────────────────────────────────────────

def fetch_seller_feedback(days_back: int = 2) -> list[dict]:
    """Return seller feedback entries from the last N days."""
    api   = _reports_api()
    start = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    end   = datetime.date.today().isoformat()

    resp  = _create_report_with_retry(
        api,
        reportType="GET_SELLER_FEEDBACK_DATA",
        dataStartTime=start + "T00:00:00Z",
        dataEndTime=end     + "T23:59:59Z",
    )
    text = _download_report(api, resp.payload["reportId"])
    if not text or not text.strip():
        return []

    reader = csv.DictReader(StringIO(text), delimiter="\t")
    return list(reader)


# ── Source 2: Product Reviews (Brand Registry only) ───────────────────────────

def fetch_product_reviews(days_back: int = 2) -> list[dict]:
    """Return product reviews — requires Brand Registry. Returns [] if unavailable."""
    from sp_api.base.exceptions import SellingApiException
    api   = _reports_api()
    start = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    end   = datetime.date.today().isoformat()

    try:
        resp = _create_report_with_retry(
            api,
            reportType="GET_PRODUCT_REVIEWS",
            dataStartTime=start + "T00:00:00Z",
            dataEndTime=end     + "T23:59:59Z",
        )
    except Exception as e:
        if "InvalidInput" in str(e) or "Invalid Report Type" in str(e):
            print("  Product reviews report unavailable (Brand Registry required) — skipping.")
            return []
        raise

    text = _download_report(api, resp.payload["reportId"])
    if not text or not text.strip():
        return []

    reader = csv.DictReader(StringIO(text), delimiter="\t")
    return list(reader)


# ── Normalise rows from either source ────────────────────────────────────────

def _normalise_feedback(row: dict, source: str) -> dict:
    """Map TSV columns from either report type to a common schema."""
    if source == "feedback":
        # GET_SELLER_FEEDBACK_DATA columns:
        # Date, Rating, Comments, Response, Order ID, Rater Email
        return {
            "id":       row.get("Order ID", str(row)),
            "rating":   int(row.get("Rating") or 0),
            "reviewer": row.get("Rater Email", "Customer"),
            "title":    "",
            "body":     row.get("Comments", ""),
            "asin":     "N/A (seller feedback)",
            "source":   "Seller Feedback",
        }
    else:
        # GET_PRODUCT_REVIEWS columns vary; try common names
        return {
            "id":       row.get("review_id") or row.get("ReviewId") or str(row),
            "rating":   int(row.get("star_rating") or row.get("Rating") or 0),
            "reviewer": row.get("reviewer_name") or row.get("ReviewerName") or "Customer",
            "title":    row.get("review_title") or row.get("ReviewTitle") or "",
            "body":     row.get("review_body")  or row.get("ReviewBody")  or "",
            "asin":     row.get("asin") or row.get("ASIN") or "UNKNOWN",
            "source":   "Product Review",
        }


# ── Email formatting ───────────────────────────────────────────────────────────

STARS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}

REFUND_TEMPLATE = """\
<p>Hi {reviewer},</p>
<p>Thank you for your feedback. We're truly sorry your experience didn't meet
expectations — this is not the standard we hold ourselves to, and we want to
make it right.</p>
<p><strong>We'd like to offer you a full refund.</strong> Please reply to this
message or reach us at
<a href="mailto:support@usplushealth.com">support@usplushealth.com</a>
and we'll process it right away.</p>
<p>If you're open to sharing more detail about what went wrong, we'd love to
hear it — your feedback helps us improve for everyone.</p>
<p>We hope to earn back your trust.<br>Warm regards,<br>US+ Health Team</p>
"""


def _build_email(reviews: list[dict]) -> tuple[str, str]:
    subject = f"🚨 {len(reviews)} Low-Star Review{'s' if len(reviews)>1 else ''} — Action Needed"
    cards   = ""
    for r in reviews:
        color    = "#e74c3c"
        star_str = STARS.get(r["rating"], str(r["rating"]))
        cards += f"""
        <div style='border:1px solid {color};border-radius:6px;padding:16px;
                    margin-bottom:20px;background:#fff8f8'>
          <p style='margin:0 0 6px'>
            <strong>Source:</strong> {r['source']} &nbsp;|&nbsp;
            <strong>ASIN:</strong> {r['asin']} &nbsp;|&nbsp;
            <strong>Rating:</strong> {star_str} ({r['rating']}/5) &nbsp;|&nbsp;
            <strong>From:</strong> {r['reviewer']}
          </p>
          {'<p style="margin:0 0 4px"><em>' + r["title"] + '</em></p>' if r["title"] else ""}
          {'<p style="margin:0 0 12px;color:#555">' + r["body"][:500] + '</p>' if r["body"] else ""}
          <details>
            <summary style='cursor:pointer;color:#2980b9;font-weight:bold'>
              📋 Draft response (click to expand)
            </summary>
            <div style='margin-top:12px;padding:12px;background:#f0f7ff;
                        border-radius:4px;font-size:14px'>
              {REFUND_TEMPLATE.format(reviewer=r["reviewer"])}
            </div>
          </details>
        </div>"""

    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:700px'>
      <h2 style='color:#e74c3c'>🚨 Low-Star Review Alert — US+ Health</h2>
      <p>The following 1–2 star rating(s) were posted recently.
         A draft refund response is included for each.</p>
      {cards}
      <p style='color:#888;font-size:12px;margin-top:24px'>
        Automated alert · US+ Health Amazon Monitor · {datetime.date.today()}
      </p>
    </body></html>"""
    return subject, html


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    print("=== Review Monitor ===")
    seen     = _load_seen()
    low_star = []

    # Source 1: Seller Feedback (always available)
    print("Checking seller feedback…")
    try:
        for row in fetch_seller_feedback():
            item = _normalise_feedback(row, "feedback")
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            if 0 < item["rating"] <= config.LOW_STAR_MAX:
                print(f"  Low-star seller feedback: {item['rating']}★")
                low_star.append(item)
    except Exception as e:
        print(f"  Seller feedback error: {e}")

    # Source 2: Product Reviews (Brand Registry only)
    print("Checking product reviews…")
    try:
        for row in fetch_product_reviews():
            item = _normalise_feedback(row, "review")
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            if 0 < item["rating"] <= config.LOW_STAR_MAX:
                print(f"  Low-star product review: {item['rating']}★ on {item['asin']}")
                low_star.append(item)
    except Exception as e:
        print(f"  Product reviews error: {e}")

    _save_seen(seen)

    if low_star:
        subject, html = _build_email(low_star)
        send_alert(subject=subject, body_html=html)
        print(f"Alert sent for {len(low_star)} low-star item(s).")
    else:
        print("No new low-star reviews or feedback.")


def _load_seen() -> set:
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE) as f:
        return set(json.load(f))


def _save_seen(seen: set):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


if __name__ == "__main__":
    run()
