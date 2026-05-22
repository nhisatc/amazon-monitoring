"""
Scan recent data and send alerts for any ASINs with ±20% change
"""

import json
import pandas as pd
from datetime import datetime
from mailer import send_alert
from config import SALES_THRESHOLD

# Load sales data
with open('data/sales_history.json') as f:
    data = json.load(f)

df = pd.DataFrame(data)
df['date'] = pd.to_datetime(df['date'])

# Get daily totals
daily_sales = df.groupby('date').agg({'units': 'sum', 'revenue': 'sum'}).reset_index()

# Get last 2 days for comparison
if len(daily_sales) >= 2:
    yesterday = daily_sales.iloc[-2]
    today = daily_sales.iloc[-1]

    daily_change = ((today['units'] - yesterday['units']) / yesterday['units'] * 100)

    print(f"Daily Change: {daily_change:+.1f}%")

    if abs(daily_change) >= SALES_THRESHOLD * 100:
        print(f"ALERT: Daily change {daily_change:+.1f}% exceeds {SALES_THRESHOLD*100:.0f}% threshold!")
    else:
        print(f"No daily alert (below {SALES_THRESHOLD*100:.0f}% threshold)")

# Check per-ASIN daily changes
print("\n" + "="*70)
print("CHECKING PER-ASIN DAILY CHANGES")
print("="*70)

asin_daily = df.groupby(['date', 'asin']).agg({'units': 'sum', 'revenue': 'sum'}).reset_index()

alerts = []
for asin in sorted(asin_daily['asin'].unique()):
    asin_data = asin_daily[asin_daily['asin'] == asin].sort_values('date')

    if len(asin_data) >= 2:
        yesterday = asin_data.iloc[-2]
        today = asin_data.iloc[-1]

        if yesterday['units'] > 0:
            pct_change = ((today['units'] - yesterday['units']) / yesterday['units'] * 100)

            print(f"\n{asin}:")
            print(f"  Yesterday: {int(yesterday['units'])} units")
            print(f"  Today: {int(today['units'])} units")
            print(f"  Change: {pct_change:+.1f}%")

            if abs(pct_change) >= SALES_THRESHOLD * 100:
                print(f"  >>> ALERT! Change exceeds {SALES_THRESHOLD*100:.0f}%")
                direction = "increase" if pct_change > 0 else "drop"
                alerts.append({
                    "asin": asin,
                    "direction": direction,
                    "pct": pct_change,
                    "current": int(today['units']),
                    "previous": int(yesterday['units']),
                })

# Send alert if any ASINs breached threshold
if alerts:
    print("\n" + "="*70)
    print(f"SENDING ALERTS FOR {len(alerts)} ASIN(S)")
    print("="*70)

    # Build HTML email
    rows = ""
    for a in alerts:
        color = "#c0392b" if a["direction"] == "drop" else "#27ae60"
        arrow = "▼" if a["direction"] == "drop" else "▲"
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;font-weight:bold'>{a['asin']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>DAILY</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{a['previous']} → {a['current']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:{color};font-weight:bold;font-size:16px'>"
            f"{arrow} {abs(a['pct']):.1f}%</td>"
            f"</tr>"
        )

    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333'>
    <h2 style='color:#e67e22'>⚠️ AMAZON SALES ALERT</h2>
    <p>The following ASINs exceeded the <strong>20% threshold</strong> for daily sales change:</p>
    <table style='border-collapse:collapse;width:100%;max-width:800px'>
      <thead>
        <tr style='background:#f0f0f0'>
          <th style='padding:8px 12px;text-align:left'>ASIN</th>
          <th style='padding:8px 12px;text-align:left'>Period</th>
          <th style='padding:8px 12px;text-align:left'>Units</th>
          <th style='padding:8px 12px;text-align:left'>Change</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <p style='margin-top:20px;padding:12px;background:#f9f9f9;border-left:4px solid #e67e22'>
      <strong>Alert triggered by:</strong> Daily sales change ≥ 20%
    </p>
    <p style='color:#888;font-size:12px;margin-top:24px'>
      US+ Health Amazon Monitor | {datetime.now().strftime('%Y-%m-%d %I:%M %p')}
    </p>
    </body></html>
    """

    send_alert(
        subject=f"ALERT: Amazon Sales Change - {len(alerts)} ASIN(s)",
        body_html=body_html
    )

    print("\nAlerts sent successfully!")
else:
    print("\nNo ASINs meet the 20% threshold for alerts.")
    print("(This is expected for stable data)")
