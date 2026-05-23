"""
Review monitor — Jungle Scout workaround
-----------------------------------------
Since Amazon blocks direct API access to individual product reviews,
this script uses Jungle Scout's product database to track the review
count and average star rating for every ASIN.

Alert logic:
  - New review(s) detected (count increased) AND rating dropped → alert
  - New review(s) detected AND current rating <= 3.5 → alert (low overall)
  - Rating drops by 0.2 or more regardless of new reviews → alert

Alert email includes the ASIN, old vs new rating, review count change,
and a pre-written refund response draft.

Run every 2–4 hours via Task Scheduler.
"""

import json
import os
import datetime
import time

from junglescout import ClientSync
from junglescout.models.parameters.marketplace import Marketplace

import config
from mailer import send_alert

SNAPSHOT_FILE = os.path.join(config.DATA_DIR, "review_snapshots.json")

# ASINs with Jungle Scout product database coverage (verified 2026-05-22)
# Note: Jungle Scout only indexes ~8 of our 31 ASINs. The others may be too new,
# niche, or not yet indexed. This is a limitation of Jungle Scout's database coverage.
INDEXED_ASINS = [
    "B0BR99MF15", "B097HP7DQ6", "B0DSCKXPQH", "B09CV925V4",
    "B097LTHS4S", "B0BJH3RD1F", "B0DDWQ1515", "B0CCMHLX72",
]

# All US+ Health ASINs (for reference; 23 don't have Jungle Scout coverage)
ALL_ASINS = [
    "B0BR99MF15", "B097HP7DQ6", "B0DSCKXPQH", "B09CV925V4",
    "B0BR9BJQK5", "B0BR9931H4", "B097LTHS4S", "B09DZ6X29K",
    "B09DZ64Q5G", "B08Y83DNZ5", "B0BJH3RD1F", "B09DZ4FW8S",
    "B0DDWQ1515", "B08Y7X8375", "B0981HX5NG", "B09CV833M4",
    "B09CV755VR", "B08Y84DK8T", "B08Y823ZVN", "B08Y82XBH3",
    "B08Y858S8Z", "B09CYSYV8G", "B0981HG4PR", "B09CN1MBX2",
    "B09CN362GY", "B09B8VN1J9", "B09B9FFHQL", "B0CCMHLX72",
    "B097HPCWCG", "B09DZ46197", "B09DZ2P2WJ",
]

UNINDEXED_ASINS = [asin for asin in ALL_ASINS if asin not in INDEXED_ASINS]

RATING_DROP_THRESHOLD  = 0.2   # alert if rating drops by this much
LOW_RATING_THRESHOLD   = 3.5   # alert if rating is at or below this


# ── Snapshot storage ───────────────────────────────────────────────────────────

def load_snapshots() -> dict:
    if not os.path.exists(SNAPSHOT_FILE):
        return {}
    with open(SNAPSHOT_FILE) as f:
        return json.load(f)


def save_snapshots(data: dict):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Jungle Scout fetch ─────────────────────────────────────────────────────────

def fetch_product_data(asins: list[str]) -> dict[str, dict]:
    """Return {asin: {reviews, rating, title}} for all ASINs we can find."""
    client = ClientSync(
        api_key_name=config.JUNGLE_SCOUT_API_KEY_NAME,
        api_key=config.JUNGLE_SCOUT_API_KEY,
        marketplace=Marketplace.US,
    )

    results = {}
    failed_asins = []

    # Query each ASIN individually (batch queries have lower hit rate)
    for asin in asins:
        try:
            response = client.product_database(include_keywords=[asin])
            if response and response.data:
                product = response.data[0]
                attr = product.attributes
                results[asin] = {
                    "reviews": attr.reviews or 0,
                    "rating":  attr.rating  or 0.0,
                    "title":   attr.title   or asin,
                }
                print(f"  {asin}: {attr.reviews} reviews, {attr.rating} star rating")
            else:
                failed_asins.append(asin)
        except Exception as e:
            print(f"  {asin}: error — {str(e)[:80]}")
            failed_asins.append(asin)
        time.sleep(1)  # be respectful to the API

    if failed_asins:
        print(f"  {len(failed_asins)} ASINs returned no data from Jungle Scout (network/API issue).")

    return results


# ── Change detection ───────────────────────────────────────────────────────────

def detect_review_changes(current: dict, previous: dict) -> list[dict]:
    alerts = []

    for asin, cur in current.items():
        if asin not in previous:
            continue  # first time seeing this ASIN — establish baseline

        prev = previous[asin]
        prev_reviews = prev.get("reviews", 0)
        prev_rating  = prev.get("rating",  0.0)
        cur_reviews  = cur.get("reviews",  0)
        cur_rating   = cur.get("rating",   0.0)

        new_reviews  = cur_reviews - prev_reviews
        rating_drop  = prev_rating - cur_rating  # positive = dropped

        should_alert = False
        reason       = ""

        if new_reviews > 0 and rating_drop > 0:
            should_alert = True
            reason = f"{new_reviews} new review(s), rating dropped {rating_drop:.1f} stars"
        elif new_reviews > 0 and cur_rating <= LOW_RATING_THRESHOLD:
            should_alert = True
            reason = f"{new_reviews} new review(s), rating is low ({cur_rating}★)"
        elif rating_drop >= RATING_DROP_THRESHOLD:
            should_alert = True
            reason = f"Rating dropped {rating_drop:.1f} stars (no new review detected yet)"

        if should_alert:
            alerts.append({
                "asin":         asin,
                "title":        cur.get("title", asin),
                "prev_rating":  prev_rating,
                "cur_rating":   cur_rating,
                "prev_reviews": prev_reviews,
                "cur_reviews":  cur_reviews,
                "new_reviews":  new_reviews,
                "reason":       reason,
            })

    return alerts


# ── Email formatting ───────────────────────────────────────────────────────────

CUSTOMER_DRAFT = """\
Hi there,

Thank you for your feedback. We're sorry your experience didn't meet expectations — we want to make it right.

We'd like to offer you a full refund. Please reach us at support@usplushealth.com and we'll process it right away, no questions asked.

If you're open to sharing what went wrong, we'd genuinely love to hear it. Your feedback helps us improve for everyone.

We hope to earn back your trust.
Warm regards,
US+ Health Team"""


def _stars(rating: float) -> str:
    """Format rating as text (e.g. '4.5 out of 5')"""
    return f"{rating} out of 5 stars"


def _build_email(alerts: list[dict]) -> tuple[str, str]:
    subject = f"ALERT: {len(alerts)} ASIN(s) — Possible Low Review — Action Needed"
    cards   = ""

    for a in alerts:
        arrow = "DOWN" if a["cur_rating"] < a["prev_rating"] else "→"
        cards += f"""
        <div style='border:1px solid #e74c3c;border-radius:6px;padding:16px;
                    margin-bottom:20px;background:#fff8f8'>
          <p style='margin:0 0 8px;font-size:15px'>
            <strong>{a['title'][:60]}</strong>
          </p>
          <p style='margin:0 0 4px'>
            <strong>ASIN:</strong> {a['asin']} &nbsp;|&nbsp;
            <strong>Rating:</strong>
            {a['prev_rating']} {arrow} <span style='color:#e74c3c;font-weight:bold'>{a['cur_rating']}</span>
          </p>
          <p style='margin:0 0 12px'>
            <strong>Reviews:</strong> {a['prev_reviews']} to {a['cur_reviews']}
            {f"<span style='color:#e74c3c'>(+{a['new_reviews']} new)</span>" if a['new_reviews'] > 0 else ""}
            &nbsp;|&nbsp; <em>{a['reason']}</em>
          </p>
          <p style='margin:0 0 4px;color:#888;font-size:12px'>
            Note: We cannot see the exact new review rating — check
            <a href='https://www.amazon.com/dp/{a['asin']}'>the listing</a>
            to confirm and respond.
          </p>
          <details>
            <summary style='cursor:pointer;color:#2980b9;font-weight:bold;margin-top:8px'>
              Draft message to customer (click to copy)
            </summary>
            <pre style='margin-top:12px;padding:12px;background:#f5f5f5;
                        border-radius:4px;font-size:13px;white-space:pre-wrap;
                        border:1px solid #ddd'>{CUSTOMER_DRAFT}</pre>
          </details>
        </div>"""

    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:700px'>
      <h2 style='color:#e74c3c'>ALERT: Possible Low-Star Review — US+ Health</h2>
      <p>The following ASIN(s) show a rating drop or new reviews with a low average.
         <strong>Try to remove via <a href='https://sellercentral.amazon.com/feedback-manager'>Feedback Manager</a> first (filter Negative → Actions → select reason).
         If removal fails, use the draft message below to offer a refund.</strong></p>
      {cards}
      <p style='color:#888;font-size:12px;margin-top:24px'>
        Automated alert via Jungle Scout · US+ Health Monitor · {datetime.date.today()}
      </p>
    </body></html>"""
    return subject, html


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    print("=== Review Monitor (Jungle Scout) ===")
    snapshots = load_snapshots()

    print(f"Monitoring {len(INDEXED_ASINS)} indexed ASINs (out of {len(ALL_ASINS)} total)")
    if UNINDEXED_ASINS:
        print(f"  Note: {len(UNINDEXED_ASINS)} ASINs not in Jungle Scout database (new/niche/not yet indexed)")

    print(f"Fetching review data via Jungle Scout…")
    current = fetch_product_data(INDEXED_ASINS)
    print(f"  Got data for {len(current)} ASINs.")

    alerts = detect_review_changes(current, snapshots)

    # Update snapshots with latest data
    snapshots.update(current)
    save_snapshots(snapshots)

    if alerts:
        subject, html = _build_email(alerts)
        send_alert(subject=subject, body_html=html)
        print(f"Alert sent for {len(alerts)} ASIN(s).")
    else:
        print("No rating drops or new low-star activity detected.")


if __name__ == "__main__":
    run()
