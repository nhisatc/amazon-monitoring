"""
Sales change monitor
--------------------
Pulls the Sales & Traffic report from SP-API (daily, child-ASIN granularity),
stores a rolling 65-day history in data/sales_history.json, then alerts
if any ASIN has a ≥20 % change day-over-day, week-over-week, month-over-month,
or year-over-year.

Uses YESTERDAY as the reference date because Amazon SP-API has a 24-48 hour
processing delay — today's data is always incomplete.

Run daily at midnight via Task Scheduler (local) or GitHub Actions (cloud).
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
    # Keep 730 days to support yearly comparisons (~400KB max)
    cutoff = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()
    df = df[df["date"] >= cutoff]
    with open(HISTORY_FILE, "w") as f:
        json.dump(df.to_dict(orient="records"), f, indent=2)


# ── Change detection ───────────────────────────────────────────────────────────

def _asin_totals(df: pd.DataFrame, start: datetime.date, end: datetime.date) -> pd.Series:
    mask = (df["date"] >= start.isoformat()) & (df["date"] <= end.isoformat())
    return df[mask].groupby("asin")["units"].sum()

def _asin_revenue(df: pd.DataFrame, start: datetime.date, end: datetime.date) -> pd.Series:
    mask = (df["date"] >= start.isoformat()) & (df["date"] <= end.isoformat())
    return df[mask].groupby("asin")["revenue"].sum()


def detect_changes(history: pd.DataFrame) -> list[dict]:
    # Use the most recent date we actually have data for as the reference point.
    # This ensures both windows always have the same number of days available —
    # comparing 5 days vs 7 days would produce false drops.
    available_dates = sorted(history["date"].unique())
    if not available_dates:
        return []
    ref_date = datetime.date.fromisoformat(available_dates[-1])
    alerts = []

    windows = [
        ("Daily",   ref_date, ref_date,
                    ref_date - datetime.timedelta(days=1), ref_date - datetime.timedelta(days=1)),
        ("Weekly",  ref_date - datetime.timedelta(days=6), ref_date,
                    ref_date - datetime.timedelta(days=13), ref_date - datetime.timedelta(days=7)),
        ("Monthly", ref_date - datetime.timedelta(days=29), ref_date,
                    ref_date - datetime.timedelta(days=59), ref_date - datetime.timedelta(days=30)),
        ("Yearly",  ref_date - datetime.timedelta(days=364), ref_date,
                    ref_date - datetime.timedelta(days=729), ref_date - datetime.timedelta(days=365)),
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
                    "cur_dates": f"{cur_start.strftime('%b %d')} – {cur_end.strftime('%b %d')}",
                    "prev_dates": f"{prev_start.strftime('%b %d')} – {prev_end.strftime('%b %d')}",
                })

    return alerts


# ── Email formatting ───────────────────────────────────────────────────────────

def _build_email(history: pd.DataFrame, alerts: list[dict]) -> str:
    available_dates = sorted(history["date"].unique())
    ref_date = datetime.date.fromisoformat(available_dates[-1])
    prev_date = ref_date - datetime.timedelta(days=1)

    # Daily summary — all products (always show every named ASIN, even if 0 sales)
    today_totals    = _asin_totals(history, ref_date, ref_date)
    yday_totals     = _asin_totals(history, prev_date, prev_date)
    today_revenue   = _asin_revenue(history, ref_date, ref_date)
    yday_revenue    = _asin_revenue(history, prev_date, prev_date)
    history_asins   = set(today_totals.index) | set(yday_totals.index)
    all_asins       = sorted(set(config.ASIN_NAMES.keys()) | history_asins)

    summary_rows = ""
    for asin in all_asins:
        cur_units  = int(today_totals.get(asin, 0))
        prev_units = int(yday_totals.get(asin, 0))
        cur_rev    = today_revenue.get(asin, 0.0)
        prev_rev   = yday_revenue.get(asin, 0.0)
        if cur_units == 0 and prev_units == 0:
            continue
        name = config.ASIN_NAMES.get(asin, asin)
        if prev_units > 0:
            upct = (cur_units - prev_units) / prev_units
            ua = "▼" if upct < 0 else "▲"
            uc = "#c0392b" if upct < 0 else "#27ae60"
            unit_chg = f"<span style='color:{uc};font-weight:bold'>{ua} {abs(upct):.0%}</span>" if abs(upct) >= config.SALES_THRESHOLD else f"<span style='color:#888'>{upct:+.0%}</span>"
        else:
            unit_chg = "<span style='color:#aaa'>—</span>"
        if prev_rev > 0:
            rpct = (cur_rev - prev_rev) / prev_rev
            ra = "▼" if rpct < 0 else "▲"
            rc = "#c0392b" if rpct < 0 else "#27ae60"
            rev_chg = f"<span style='color:{rc};font-weight:bold'>{ra} {abs(rpct):.0%}</span>" if abs(rpct) >= config.SALES_THRESHOLD else f"<span style='color:#888'>{rpct:+.0%}</span>"
        else:
            rev_chg = "<span style='color:#aaa'>—</span>"
        summary_rows += (
            f"<tr>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:12px;color:#555'>{name}</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:11px;color:#888'>{asin}</td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:right'>{prev_units}<br><span style='color:#888;font-size:11px'>${prev_rev:,.2f}</span></td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:right'>{cur_units}<br><span style='color:#888;font-size:11px'>${cur_rev:,.2f}</span></td>"
            f"<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:right'>{unit_chg}<br><span style='font-size:11px'>{rev_chg}</span></td>"
            f"</tr>"
        )

    # MoM and YoY sections — always show all products
    def _period_section(label, cur_start, cur_end, prev_start, prev_end):
        u_cur  = _asin_totals(history, cur_start, cur_end)
        u_prev = _asin_totals(history, prev_start, prev_end)
        r_cur  = _asin_revenue(history, cur_start, cur_end)
        r_prev = _asin_revenue(history, prev_start, prev_end)
        asins  = sorted(set(config.ASIN_NAMES.keys()) | set(u_cur.index) | set(u_prev.index))
        rows   = ""
        for asin in asins:
            uc = int(u_cur.get(asin, 0)); up = int(u_prev.get(asin, 0))
            rc = r_cur.get(asin, 0.0);   rp = r_prev.get(asin, 0.0)
            if uc == 0 and up == 0:
                continue
            name = config.ASIN_NAMES.get(asin, asin)
            if up > 0:
                upct = (uc - up) / up
                ua = "▼" if upct < 0 else "▲"
                col = "#c0392b" if upct < 0 else "#27ae60"
                uchg = f"<span style='color:{col};font-weight:bold'>{ua} {abs(upct):.0%}</span>" if abs(upct) >= config.SALES_THRESHOLD else f"<span style='color:#888'>{upct:+.0%}</span>"
            else:
                uchg = "<span style='color:#aaa'>—</span>"
            if rp > 0:
                rpct = (rc - rp) / rp
                ra = "▼" if rpct < 0 else "▲"
                col = "#c0392b" if rpct < 0 else "#27ae60"
                rchg = f"<span style='color:{col};font-weight:bold'>{ra} {abs(rpct):.0%}</span>" if abs(rpct) >= config.SALES_THRESHOLD else f"<span style='color:#888'>{rpct:+.0%}</span>"
            else:
                rchg = "<span style='color:#aaa'>—</span>"
            rows += (
                f"<tr>"
                f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:12px;color:#555'>{name}</td>"
                f"<td style='padding:5px 10px;border-bottom:1px solid #eee;font-size:11px;color:#888'>{asin}</td>"
                f"<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:right'>{up}<br><span style='color:#888;font-size:11px'>${rp:,.2f}</span></td>"
                f"<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:right'>{uc}<br><span style='color:#888;font-size:11px'>${rc:,.2f}</span></td>"
                f"<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:right'>{uchg}<br><span style='font-size:11px'>{rchg}</span></td>"
                f"</tr>"
            )
        date_range = f"{cur_start.strftime('%b %d')} – {cur_end.strftime('%b %d')} vs {prev_start.strftime('%b %d')} – {prev_end.strftime('%b %d')}"
        return f"""
    <h3 style='color:#2c3e50;margin-top:28px'>{label} Comparison <span style='font-weight:normal;font-size:12px;color:#888'>({date_range})</span></h3>
    <table style='border-collapse:collapse;width:100%;max-width:700px'>
      <thead>
        <tr style='background:#f0f0f0'>
          <th style='padding:7px 10px;text-align:left;font-size:12px'>Product</th>
          <th style='padding:7px 10px;text-align:left;font-size:12px'>ASIN</th>
          <th style='padding:7px 10px;text-align:right;font-size:12px'>Previous<br><span style='font-weight:normal;color:#888'>units / $</span></th>
          <th style='padding:7px 10px;text-align:right;font-size:12px'>Current<br><span style='font-weight:normal;color:#888'>units / $</span></th>
          <th style='padding:7px 10px;text-align:right;font-size:12px'>Change<br><span style='font-weight:normal;color:#888'>units / $</span></th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""

    mom_section = _period_section(
        "Monthly (MoM)",
        ref_date - datetime.timedelta(days=29), ref_date,
        ref_date - datetime.timedelta(days=59), ref_date - datetime.timedelta(days=30),
    )
    yoy_section = _period_section(
        "Yearly (YoY)",
        ref_date - datetime.timedelta(days=364), ref_date,
        ref_date - datetime.timedelta(days=729), ref_date - datetime.timedelta(days=365),
    )

    return f"""
    <html><body style='font-family:Arial,sans-serif;color:#333'>
    <h2 style='color:#2c3e50'>Amazon Daily Sales Report — US+ Health</h2>
    <p style='color:#555;font-size:13px'>
      Reference date: <strong>{ref_date.strftime('%b %d, %Y')}</strong> vs previous day
      ({prev_date.strftime('%b %d')})
    </p>
    <table style='border-collapse:collapse;width:100%;max-width:700px'>
      <thead>
        <tr style='background:#f0f0f0'>
          <th style='padding:7px 10px;text-align:left;font-size:12px'>Product</th>
          <th style='padding:7px 10px;text-align:left;font-size:12px'>ASIN</th>
          <th style='padding:7px 10px;text-align:right;font-size:12px'>Yesterday<br><span style='font-weight:normal;color:#888'>units / $</span></th>
          <th style='padding:7px 10px;text-align:right;font-size:12px'>Today<br><span style='font-weight:normal;color:#888'>units / $</span></th>
          <th style='padding:7px 10px;text-align:right;font-size:12px'>Change<br><span style='font-weight:normal;color:#888'>units / $</span></th>
        </tr>
      </thead>
      <tbody>{summary_rows}</tbody>
    </table>
    {mom_section}
    {yoy_section}
    <p style='color:#aaa;font-size:11px;margin-top:24px'>
      Automated report from US+ Health Amazon Monitor · {datetime.date.today()}
    </p>
    </body></html>
    """


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    # Amazon SP-API needs ~48 hours to produce ASIN-level breakdowns.
    # "yesterday" (1 day ago) often has date-level totals but empty ASIN data.
    # We fetch the TWO most recent days that aren't already stored, which
    # ensures we always pick up data as soon as it becomes available.
    history = load_history()
    new_data = False

    for days_ago in range(1, 4):  # try 1, 2, 3 days ago
        target = datetime.date.today() - datetime.timedelta(days=days_ago)
        if target.isoformat() in history["date"].values:
            continue

        print(f"Fetching sales report for {target}…")
        df_day = fetch_sales_report(target)

        if df_day.empty:
            print(f"No ASIN-level data for {target} — not ready yet, skipping.")
            continue

        history = pd.concat([history, df_day], ignore_index=True)
        new_data = True
        print(f"Added {len(df_day)} rows for {target}.")

    if new_data:
        save_history(history)

    alerts = detect_changes(history)
    alerts = [a for a in alerts if a["current"] > 0]

    print(f"Sending daily report ({len(alerts)} significant change(s)).")
    send_alert(
        subject=f"Amazon Daily Sales Report — {datetime.date.today().strftime('%b %d, %Y')}",
        body_html=_build_email(history, alerts),
    )


if __name__ == "__main__":
    run()
