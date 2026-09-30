"""
One-time backfill of historical SP-API sales data.

Fills the gap between 2 years ago and the start of our existing daily history,
enabling proper YoY comparisons in the daily sales report.

SP-API rate limit: 1 report/minute. For ~18 monthly chunks this takes ~20 min.
"""

import datetime
import time
import pandas as pd
import sales_monitor

CHUNK_DAYS = 30


def run_backfill():
    history = sales_monitor.load_history()

    if history.empty:
        print("No existing history — run the main monitor first.")
        return

    existing_dates = set(history["date"].values)
    earliest = datetime.date.fromisoformat(sorted(history["date"].unique())[0])
    two_years_ago = datetime.date.today() - datetime.timedelta(days=730)

    if earliest <= two_years_ago:
        print(f"History already covers 2 years (earliest: {earliest}). Nothing to backfill.")
        return

    print(f"Existing history starts : {earliest}")
    print(f"Two years ago           : {two_years_ago}")
    print(f"Gap to fill             : {two_years_ago} → {earliest - datetime.timedelta(days=1)}")

    # Generate 30-day chunks from oldest → newest
    chunks = []
    cur = two_years_ago
    while cur < earliest:
        end = min(cur + datetime.timedelta(days=CHUNK_DAYS - 1),
                  earliest - datetime.timedelta(days=1))
        chunks.append((cur, end))
        cur = end + datetime.timedelta(days=1)

    print(f"\nTotal chunks: {len(chunks)}")
    print(f"Estimated time: ~{len(chunks)} minutes\n")

    new_rows = []
    for i, (start, end) in enumerate(chunks, 1):
        if start.isoformat() in existing_dates:
            print(f"[{i:2}/{len(chunks)}] {start} already in history, skipping.")
            continue

        print(f"[{i:2}/{len(chunks)}] Fetching {start} → {end} ...", end=" ", flush=True)
        try:
            df = sales_monitor.fetch_sales_report_range(start, end)
            if df.empty:
                print("no data returned.")
            else:
                new_rows.append(df)
                print(f"OK — {len(df)} rows.")
        except Exception as exc:
            print(f"ERROR: {exc}")

        if i < len(chunks):
            print(f"         waiting 65 s for rate limit…", end="\r", flush=True)
            time.sleep(65)

    if new_rows:
        combined = pd.concat([history] + new_rows, ignore_index=True)
        combined = (combined
                    .sort_values(["date", "asin"])
                    .drop_duplicates(["date", "asin"], keep="last")
                    .reset_index(drop=True))
        sales_monitor.save_history(combined)
        total = sum(len(r) for r in new_rows)
        print(f"\n✓ Saved {total} new rows.")
        print(f"  History now spans {combined['date'].min()} → {combined['date'].max()}")
    else:
        print("\nNothing new to save.")


if __name__ == "__main__":
    run_backfill()
