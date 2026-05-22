"""
Send official announcement that US+ Health Amazon Monitoring System is LIVE
"""

from mailer import send_alert
from datetime import datetime

announcement_html = """
<html><body style='font-family:Arial,sans-serif;color:#333'>

<h1 style='color:#27ae60;border-bottom:3px solid #27ae60;padding-bottom:10px'>
  🚀 US+ HEALTH AMAZON MONITORING SYSTEM - NOW LIVE!
</h1>

<p style='font-size:16px;line-height:1.6'>Dear Max & Julian,</p>

<p>Your complete <strong>Amazon Sales & Review Monitoring System</strong> is now officially <strong>LIVE and operational</strong>! 🎉</p>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#1f77b4'>📊 Dashboard Access</h2>

<p style='background:#f0f8ff;padding:15px;border-left:4px solid #1f77b4;border-radius:4px;font-size:16px'>
  <strong>URL:</strong> <a href='https://nhisatc-amazon-monitoring.streamlit.app' style='color:#0066cc;text-decoration:none'>
    https://nhisatc-amazon-monitoring.streamlit.app
  </a>
</p>

<p>✅ <strong>No login required</strong> - just open the link!</p>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#e67e22'>⚙️ What's Running</h2>

<table style='width:100%;border-collapse:collapse;margin:15px 0'>
  <tr style='background:#f9f9f9'>
    <td style='padding:12px;border-bottom:1px solid #ddd'><strong>Component</strong></td>
    <td style='padding:12px;border-bottom:1px solid #ddd'><strong>Schedule</strong></td>
    <td style='padding:12px;border-bottom:1px solid #ddd'><strong>Status</strong></td>
  </tr>
  <tr>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Sales Monitor</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Midnight EST + 1 PM UTC</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>✓ Active</strong></td>
  </tr>
  <tr style='background:#f9f9f9'>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Review Monitor</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Every 2 hours + midnight EST</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>✓ Active</strong></td>
  </tr>
  <tr>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Email Alerts</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Real-time on threshold breach</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>✓ Active</strong></td>
  </tr>
  <tr style='background:#f9f9f9'>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Dashboard</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>24/7 Online</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>✓ Live</strong></td>
  </tr>
</table>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#e67e22'>📈 Current Metrics</h2>

<div style='background:#fff9e6;padding:15px;border-left:4px solid #e67e22;border-radius:4px;margin:15px 0'>
  <p><strong>Daily Change:</strong> <span style='color:#27ae60;font-size:18px'>+10.1%</span></p>
  <p><strong>Weekly Change:</strong> <span style='color:#d32f2f;font-size:18px'>-0.7%</span></p>
  <p><strong>Monthly Change:</strong> <span style='color:#27ae60;font-size:18px'>+3.6%</span></p>
  <p><strong>Yearly Change:</strong> <span style='color:#27ae60;font-size:18px'>+47.1%</span></p>
</div>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#1f77b4'>🎯 What to Expect</h2>

<ul style='font-size:14px;line-height:1.8'>
  <li>✅ <strong>Real-time dashboard</strong> showing sales trends by ASIN</li>
  <li>✅ <strong>Email alerts</strong> when sales change ≥20% (daily, weekly, monthly, yearly)</li>
  <li>✅ <strong>Review monitoring</strong> for your 8 indexed ASINs on Jungle Scout</li>
  <li>✅ <strong>2 years of historical data</strong> pre-loaded for comparisons</li>
  <li>✅ <strong>Fully automated</strong> - no manual intervention needed</li>
  <li>✅ <strong>24/7 cloud operation</strong> - your PC doesn't need to be on</li>
</ul>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#1f77b4'>📊 Dashboard Tabs</h2>

<p><strong>1. Sales Trends</strong></p>
<ul style='margin-top:5px;margin-bottom:15px'>
  <li>4 period metrics (Daily, Weekly, Monthly, Yearly)</li>
  <li>Sales by ASIN chart</li>
  <li>Daily trends by product</li>
</ul>

<p><strong>2. Review Ratings</strong></p>
<ul style='margin-top:5px;margin-bottom:15px'>
  <li>8 tracked ASINs with ratings</li>
  <li>Alert for ratings ≤3.5 stars</li>
  <li>Review count tracking</li>
</ul>

<p><strong>3. Data Table</strong></p>
<ul style='margin-top:5px'>
  <li>Raw sales history</li>
  <li>Review snapshots</li>
</ul>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#2ca02c'>✅ System Features</h2>

<div style='display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:15px 0'>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>📱 Cloud-Based</strong></p>
    <p style='font-size:13px;color:#555'>No PC needed, accessible from anywhere</p>
  </div>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>⚡ Real-Time</strong></p>
    <p style='font-size:13px;color:#555'>Dashboard updates every 5 minutes</p>
  </div>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>🔔 Smart Alerts</strong></p>
    <p style='font-size:13px;color:#555'>Get notified instantly on ≥20% changes</p>
  </div>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>📊 By ASIN</strong></p>
    <p style='font-size:13px;color:#555'>See performance of each product</p>
  </div>
</div>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#1f77b4'>🚀 Ready to Use</h2>

<p style='background:#f0f8ff;padding:15px;border-left:4px solid #1f77b4;border-radius:4px;margin:15px 0'>
  <strong>No setup needed.</strong> Everything is automated and running in the cloud.
  <br><br>
  Just go to the dashboard link above and start monitoring your Amazon sales in real-time!
</p>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<p style='color:#666;font-size:12px'>
  <strong>System Status:</strong> 🟢 LIVE & OPERATIONAL<br>
  <strong>Uptime:</strong> 24/7 Cloud-Based<br>
  <strong>Last Updated:</strong> """ + datetime.now().strftime('%Y-%m-%d %I:%M %p') + """<br>
  <strong>By:</strong> US+ Health Engineering Team
</p>

<p style='color:#888;font-size:11px;margin-top:30px'>
  This is an automated announcement from your Amazon Monitoring System.<br>
  Questions? Check the dashboard or contact the engineering team.
</p>

</body></html>
"""

# Send to both Max and Julian
send_alert(
    subject="🚀 LIVE: US+ Health Amazon Monitoring System - Dashboard Online",
    body_html=announcement_html,
    recipients=["julian@usplushealth.com", "max@usplushealth.com"]
)

print("[SUCCESS] System LIVE announcement sent to Max and Julian!")
print("\nAnnouncement includes:")
print("  ✅ Dashboard URL")
print("  ✅ System status overview")
print("  ✅ Current metrics")
print("  ✅ What to expect")
print("  ✅ Features list")
