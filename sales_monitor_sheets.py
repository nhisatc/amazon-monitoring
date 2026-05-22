"""
Sales change monitor — Google Sheets fallback
----------------------------------------------
Use this version while SP-API access is pending.

How it works:
  1. Nhisa downloads the "Detail Page Sales and Traffic by Child ASIN" report
     from Seller Central → Reports → Business Reports, saves it as a CSV,
     and drops it in the /data/uploads/ folder (or uploads to a Google Sheet).
  2. This script reads the CSV(s), computes daily/weekly/monthly % changes
     per ASIN, and emails an alert for any ≥20% move.

Seller Central report path:
  Reports → Business Reports → By ASIN → Detail Page Sales and Traffic by Child ASIN
  → Set date range to last 60 days → Download (.csv)

Run manually after each upload, or schedule via Task Scheduler.
"""

import os
import glob
import datetime
import pandas as pd
from mailer import send_alert
import config

UPLOAD_DIR  = os.path.join(config.DATA_DIR, "uploads")
HISTORY_FILE = os.path.join(config.DATA_DIR, "sales_history_sheets.csv")

# Seller Central CSV column names (these are the actual header names in the export)
COL_DATE    = "(Parent) ASIN"          # used only for detection; real date col below
COL_ASIN    = "Child ASIN"
COL_UNITS   = "Units Ordered"
COL_REVENUE = "Ordered Product Sales"
COL_DATE2   = "Date"                   # present in the "by date" version of the report


# ── CSV ingestion ──────────────────────────────────────────────────────────────

def _clean_currency(val) -> float:
    """Strip $ and commas from currency strings."""
    if isinstance(val, str):
        return float(val.replace("$", "").replace(",", "").strip() or 0)
    return float(val or 0)


def load_csv(path: str) -> pd.DataFrame:
    """Load a Seller Central Business Report CSV and normalise columns."""
    df = pd.read_csv(path, thousands=",")
    df.columns = df.columns.str.strip()

    # Detect which date column is present
    if COL_DATE2 in df.columns:
        df["date"] = pd.to_datetime(df[COL_DATE2]).dt.date.astype(str)
    elif "Sessions - Total" in df.columns:
        # Summary report without a Date column — use filename date if parseable
        fname = os.path.basename(path)
        try:
            date_str = fname[:10]   # expects YYYY-MM-DD_...csv naming
            datetime.date.fromisoformat(date_str)
            df["date"] = date_str
        except ValueError:
            df["date"] = datetime.date.today().isoformat()
    else:
        df["date"] = datetime.date.today().isoformat()

    asin_col = COL_ASIN if COL_ASIN in df.columns else "(Parent) ASIN"
    df["asin"]    = df[asin_col].astype(str).str.strip()
    df["units"]   = pd.to_numeric(df.get(COL_UNITS, 0), errors="coerce").fillna(0).astype(int)
    df["revenue"] = df.get(COL_REVENUE, "0").apply(_clean_currency)

    return df[["date", "asin", "units", "revenue"]]


def ingest_new_uploads() -> int:
    """Load any CSVs in /data/uploads/, merge into history, return rows added."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    csv_files = sorted(glob.glob(os.path.join(UPLOAD_DIR, "*.csv")))
    if not csv_files:
        print(f"No CSV files found in {UPLOAD_DIR}")
        return 0

    # Load existing history
    if os.path.exists(HISTORY_FILE):
        history = pd.read_csv(HISTORY_FILE)
    else:
        history = pd.DataFrame(columns=["date", "asin", "units", "revenue"])

    rows_added = 0
    for path in csv_files:
        print(f"  Ingesting {os.path.basename(path)}…")
        new_df = load_csv(path)

        # Drop rows already in history (same date + asin)
        existing_keys = set(zip(history["date"], history["asin"]))
        new_df = new_df[~new_df.apply(lambda r: (r["date"], r["asin"]) in existing_keys, axis=1)]

        if not new_df.empty:
            history  = pd.concat([history, new_df], ignore_index=True)
            rows_added += len(new_df)

    # Keep only last 65 days
    cutoff  = (datetime.date.today() - datetime.timedelta(days=65)).isoformat()
    history = history[history["date"] >= cutoff]
    history.to_csv(HISTORY_FILE, index=False)
    print(f"  {rows_added} new rows added to history.")
    return rows_added


# ── Change detection (same logic as SP-API version) ───────────────────────────

def _asin_totals(df: pd.DataFrame, start: datetime.date, end: datetime.date) -> pd.Series:
    mask = (df["date"] >= start.isoformat()) & (df["date"] <= end.isoformat())
    return df[mask].groupby("asin")["units"].sum()


def detect_changes(history: pd.DataFrame) -> list[dict]:
    today  = datetime.date.today()
    alerts = []

    windows = [
        ("Daily",
         today - datetime.timedelta(days=1), today - datetime.timedelta(days=1),
         today - datetime.timedelta(days=2), today - datetime.timedelta(days=2)),
        ("Weekly",
         today - datetime.timedelta(days=6), today,
         today - datetime.timedelta(days=13), today - datetime.timedelta(days=7)),
        ("Monthly",
         today - datetime.timedelta(days=29), today,
         today - datetime.timedelta(days=59), today - datetime.timedelta(days=30)),
    ]

    for label, cur_start, cur_end, prev_start, prev_end in windows:
        current  = _asin_totals(history, cur_start, cur_end)
        previous = _asin_totals(history, prev_start, prev_end)

        for asin in set(current.index) | set(previous.index):
            cur_val  = current.get(asin, 0)
            prev_val = previous.get(asin, 0)
            if prev_val == 0:
                continue
            pct = (cur_val - prev_val) / prev_val
            if abs(pct) >= config.SALES_THRESHOLD:
                alerts.append({
                    "window":    label,
                    "asin":      asin,
                    "direction": "increase" if pct > 0 else "drop",
                    "pct":       pct,
                    "current":   cur_val,
                    "previous":  prev_val,
                })
    return alerts


# ── Email (same template as SP-API version) ────────────────────────────────────

def _build_email(alerts: list[dict]) -> str:
    rows = ""
    for a in alerts:
        color = "#c0392b" if a["direction"] == "drop" else "#27ae60"
        arrow = "▼" if a["direction"] == "drop" else "▲"
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{a['asin']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{a['window']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;"
            f"color:{color};font-weight:bold'>{arrow} {abs(a['pct']):.1%}</td>"
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
      Automated alert · US+ Health Amazon Monitor · {datetime.date.today()}
    </p>
    </body></html>
    """


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    print("=== Sales Monitor (Sheets/CSV fallback) ===")
    print(f"Looking for CSVs in: {UPLOAD_DIR}")
    ingest_new_uploads()

    if not os.path.exists(HISTORY_FILE):
        print("No history yet — add CSVs to data/uploads/ and re-run.")
        return

    history = pd.read_csv(HISTORY_FILE)
    alerts  = detect_changes(history)

    if alerts:
        print(f"Sending alert: {len(alerts)} change(s) detected.")
        send_alert(
            subject=f"⚠️ Amazon Sales Alert — {len(alerts)} change(s) detected",
            body_html=_build_email(alerts),
        )
    else:
        print("No significant sales changes detected.")


if __name__ == "__main__":
    run()
