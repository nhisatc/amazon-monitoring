"""
Sales change monitor
--------------------
Pulls the Sales & Traffic report from SP-API (daily ASIN granularity),
stores a rolling history in data/sales_history.json, then alerts
if any ASIN has a ≥20 % change day-over-day, week-over-week, or
month-over-month.

Run daily (e.g. 8 AM) via Task Scheduler or Cloud Scheduler.
"""

import json
import os
import datetime
import time
import gzip
from io import StringIO, BytesIO
import certifi
import httpx

# Patch httpx.Client to always use certifi's CA bundle on Windows
_orig_httpx_client = httpx.Client
class _CertifiedClient(_orig_httpx_client):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("verify", certifi.where())
        super().__init__(*args, **kwargs)
httpx.Client = _CertifiedClient

import pandas as pd
from sp_api.api import Reports
from sp_api.base import Marketplaces

import config
from mailer import send_alert

HISTORY_FILE = os.path.join(config.DATA_DIR, "sales_history.json")


# ── SP-API helpers ─────────────────────────────────────────────────────────────

def _marketplace():
    # Map the marketplace ID string to the Marketplaces enum value
    for m in Marketplaces:
        if m.value[0] == config.MARKETPLACE_ID:
            return m
    return Marketplaces.US


def fetch_sales_report(date: datetime.date) -> pd.DataFrame:
    """Request and download a single-day Sales & Traffic report."""
    from sp_api.base.exceptions import SellingApiRequestThrottledException
    reports_api = Reports(credentials=config.SP_API_CREDENTIALS, marketplace=_marketplace(), verify=config.SSL_VERIFY)

    # Retry up to 5 times on throttling with 60s backoff
    for attempt in range(5):
        try:
            response = reports_api.create_report(
                reportType="GET_SALES_AND_TRAFFIC_REPORT",
                dataStartTime=date.isoformat() + "T00:00:00Z",
                dataEndTime=date.isoformat() + "T23:59:59Z",
                reportOptions={"dateGranularity": "DAY", "asinGranularity": "CHILD"},
            )
            break
        except SellingApiRequestThrottledException:
            wait = 60 * (attempt + 1)
            print(f"Rate limited — waiting {wait}s before retry {attempt + 1}/5…")
            time.sleep(wait)
    else:
        raise RuntimeError("Exceeded retry limit due to rate limiting. Try again in 15 minutes.")
    report_id = response.payload["reportId"]

    # Poll until the report is done (usually < 60 s)
    for _ in range(30):
        time.sleep(10)
        status = reports_api.get_report(report_id).payload
        if status["processingStatus"] == "DONE":
            break
        if status["processingStatus"] in ("FATAL", "CANCELLED"):
            raise RuntimeError(f"Report {report_id} failed: {status['processingStatus']}")

    doc_id   = status["reportDocumentId"]
    doc     = reports_api.get_report_document(doc_id)
    payload = doc.payload
    doc_url = payload["url"]
    is_gzip = payload.get("compressionAlgorithm", "").upper() == "GZIP"

    resp = httpx.get(doc_url, verify=certifi.where(), timeout=60)
    resp.raise_for_status()

    raw_bytes = resp.content
    if is_gzip:
        raw_bytes = gzip.decompress(raw_bytes)

    raw_json = json.loads(raw_bytes.decode("utf-8"))

    rows = []
    for entry in raw_json.get("salesAndTrafficByAsin", []):
        asin  = entry.get("childAsin") or entry.get("parentAsin", "UNKNOWN")
        sales = entry.get("salesByAsin", {})
        rows.append({
            "asin":   asin,
            "units":  sales.get("unitsOrdered", 0),
            "revenue": sales.get("orderedProductSales", {}).get("amount", 0.0),
        })

    df = pd.DataFrame(rows)
    df["date"] = date.isoformat()
    return df


# ── History storage ────────────────────────────────────────────────────────────

HISTORY_COLS = ["date", "asin", "units", "revenue"]

def load_history() -> pd.DataFrame:
    empty = pd.DataFrame(columns=HISTORY_COLS)
    if not os.path.exists(HISTORY_FILE):
        return empty
    with open(HISTORY_FILE) as f:
        records = json.load(f)
    if not records:
        return empty
    df = pd.DataFrame(records)
    # Ensure all expected columns exist
    for col in HISTORY_COLS:
        if col not in df.columns:
            df[col] = 0 if col in ("units", "revenue") else ""
    return df


def save_history(df: pd.DataFrame):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    # Keep only the last 65 days to limit file size
    cutoff = (datetime.date.today() - datetime.timedelta(days=65)).isoformat()
    df = df[df["date"] >= cutoff]
    with open(HISTORY_FILE, "w") as f:
        json.dump(df.to_dict(orient="records"), f, indent=2)


# ── Change detection ───────────────────────────────────────────────────────────

def _asin_totals(df: pd.DataFrame, start: datetime.date, end: datetime.date) -> pd.Series:
    mask = (df["date"] >= start.isoformat()) & (df["date"] <= end.isoformat())
    return df[mask].groupby("asin")["units"].sum()


def detect_changes(history: pd.DataFrame) -> list[dict]:
    # Use yesterday as reference — today's data is never complete due to
    # Amazon SP-API's 24-48 hour processing delay.
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    alerts    = []

    windows = [
        ("Daily",   yesterday, yesterday,
                    yesterday - datetime.timedelta(days=1), yesterday - datetime.timedelta(days=1)),
        ("Weekly",  yesterday - datetime.timedelta(days=6), yesterday,
                    yesterday - datetime.timedelta(days=13), yesterday - datetime.timedelta(days=7)),
        ("Monthly", yesterday - datetime.timedelta(days=29), yesterday,
                    yesterday - datetime.timedelta(days=59), yesterday - datetime.timedelta(days=30)),
        ("Yearly",  yesterday - datetime.timedelta(days=364), yesterday,
                    yesterday - datetime.timedelta(days=729), yesterday - datetime.timedelta(days=365)),
    ]

    for label, cur_start, cur_end, prev_start, prev_end in windows:
        current  = _asin_totals(history, cur_start, cur_end)
        previous = _asin_totals(history, prev_start, prev_end)

        all_asins = set(current.index) | set(previous.index)
        for asin in all_asins:
            cur_val  = current.get(asin, 0)
            prev_val = previous.get(asin, 0)

            if prev_val == 0:
                continue  # can't compute % change from zero

            pct = (cur_val - prev_val) / prev_val
            if abs(pct) >= config.SALES_THRESHOLD:
                direction = "increase" if pct > 0 else "drop"
                alerts.append({
                    "window":    label,
                    "asin":      asin,
                    "direction": direction,
                    "pct":       pct,
                    "current":   cur_val,
                    "previous":  prev_val,
                })

    return alerts


# ── Email formatting ───────────────────────────────────────────────────────────

def _build_email(alerts: list[dict]) -> str:
    rows = ""
    for a in alerts:
        color = "#c0392b" if a["direction"] == "drop" else "#27ae60"
        arrow = "▼" if a["direction"] == "drop" else "▲"
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{a['asin']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{a['window']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:{color};font-weight:bold'>"
            f"{arrow} {abs(a['pct']):.1%}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>"
            f"{int(a['previous'])} → {int(a['current'])} units</td>"
            f"</tr>"
        )

    return f"""
    <html><body style='font-family:Arial,sans-serif;color:#333'>
    <h2 style='color:#e67e22'>⚠️ Amazon Sales Alert — US+ Health</h2>
    <p>The following ASINs have a <strong>≥20% change</strong> in units sold:</p>
    <table style='border-collapse:collapse;width:100%;max-width:700px'>
      <thead>
        <tr style='background:#f0f0f0'>
          <th style='padding:8px 12px;text-align:left'>ASIN</th>
          <th style='padding:8px 12px;text-align:left'>Window</th>
          <th style='padding:8px 12px;text-align:left'>Change</th>
          <th style='padding:8px 12px;text-align:left'>Units</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <p style='color:#888;font-size:12px;margin-top:24px'>
      Automated alert from US+ Health Amazon Monitor · {datetime.date.today()}
    </p>
    </body></html>
    """


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    # Fetch yesterday's data — Amazon SP-API has a 24-48 hour processing
    # delay, so today's numbers are almost always incomplete / zero.
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    history   = load_history()

    if yesterday.isoformat() not in history["date"].values:
        print(f"Fetching sales report for {yesterday}…")
        df_yesterday = fetch_sales_report(yesterday)
        history = pd.concat([history, df_yesterday], ignore_index=True)
        save_history(history)
    else:
        print(f"Sales data for {yesterday} already in history, skipping fetch.")

    alerts = detect_changes(history)

    # Safety check: drop any alert where the current-period total is 0 —
    # that almost always means the data hasn't been processed yet.
    alerts = [a for a in alerts if a["current"] > 0]

    if alerts:
        print(f"Sending alert: {len(alerts)} ASIN/window combinations triggered.")
        send_alert(
            subject=f"⚠️ Amazon Sales Alert — {len(alerts)} change(s) detected",
            body_html=_build_email(alerts),
        )
    else:
        print("No significant sales changes detected.")


if __name__ == "__main__":
    run()
