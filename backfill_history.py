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
    print(f"Gap to fill             : {two_years_ago} to {earliest - datetime.timedelta(days=1)}")

    # Generate 30-day chunks from oldest to newest
    chunks = []
    cur = two_years_ago
    while cur < earliest:
        end = min(cur + datetime.timedelta(days=CHUNK_DAYS - 1),
                  earliest - datetime.timedelta(days=1))
        chunks.append((cur, end))
        cur = end + datetime.timedelta(days=1)

    print(f"\nTotal chunks: {len(chunks)}")
    print(f"Estimated time: ~{len(chunks)} minutes\n")

    total_saved = 0
    for i, (start, end) in enumerate(chunks, 1):
        # Reload history each iteration so skips stay accurate after saves
        history = sales_monitor.load_history()
        existing_dates = set(history["date"].values)

        if start.isoformat() in existing_dates:
            print(f"[{i:2}/{len(chunks)}] {start} already in history, skipping.")
            continue

        print(f"[{i:2}/{len(chunks)}] Fetching {start} to {end} ...", end=" ", flush=True)
        try:
            df = sales_monitor.fetch_sales_report_range(start, end)
            if df.empty:
                print("no data returned.")
            else:
                combined = pd.concat([history, df], ignore_index=True)
                combined = (combined
                            .sort_values(["date", "asin"])
                            .drop_duplicates(["date", "asin"], keep="last")
                            .reset_index(drop=True))
                sales_monitor.save_history(combined)
                total_saved += len(df)
                print(f"OK — {len(df)} rows saved.")
        except Exception as exc:
            print(f"ERROR: {exc}")

        if i < len(chunks):
            print(f"         waiting 65 s for rate limit...", end="\r", flush=True)
            time.sleep(65)

    if total_saved:
        history = sales_monitor.load_history()
        print(f"\nDone. Saved {total_saved} new rows total.")
        print(f"  History now spans {history['date'].min()} to {history['date'].max()}")
    else:
        print("\nNothing new to save.")


if __name__ == "__main__":
    run_backfill()
