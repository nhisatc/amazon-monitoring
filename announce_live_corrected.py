"""
Send CORRECTED announcement with the correct dashboard URL
"""

from mailer import send_alert
from datetime import datetime

announcement_html = """
<html><body style='font-family:Arial,sans-serif;color:#333'>

<h1 style='color:#27ae60;border-bottom:3px solid #27ae60;padding-bottom:10px'>
  US+ HEALTH AMAZON MONITORING SYSTEM - NOW LIVE!
</h1>

<p style='font-size:16px;line-height:1.6'>Dear Max & Julian,</p>

<p>Your complete <strong>Amazon Sales & Review Monitoring System</strong> is now officially <strong>LIVE and operational!</strong></p>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#1f77b4'>DASHBOARD ACCESS</h2>

<p style='background:#f0f8ff;padding:15px;border-left:4px solid #1f77b4;border-radius:4px;font-size:18px;font-weight:bold'>
  <a href='https://usplusdashboardmonitoring.streamlit.app/' style='color:#0066cc;text-decoration:none'>
    https://usplusdashboardmonitoring.streamlit.app/
  </a>
</p>

<p style='background:#e8f5e9;padding:12px;border-radius:4px'>
  <strong>No login required</strong> - just click the link and start monitoring!
</p>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#e67e22'>WHAT'S RUNNING</h2>

<table style='width:100%;border-collapse:collapse;margin:15px 0'>
  <tr style='background:#f9f9f9'>
    <td style='padding:12px;border-bottom:1px solid #ddd'><strong>Component</strong></td>
    <td style='padding:12px;border-bottom:1px solid #ddd'><strong>Schedule</strong></td>
    <td style='padding:12px;border-bottom:1px solid #ddd'><strong>Status</strong></td>
  </tr>
  <tr>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Sales Monitor</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Midnight EST + 1 PM UTC</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>ACTIVE</strong></td>
  </tr>
  <tr style='background:#f9f9f9'>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Review Monitor</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Every 2 hours + midnight EST</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>ACTIVE</strong></td>
  </tr>
  <tr>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Email Alerts</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Real-time on threshold breach</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>ACTIVE</strong></td>
  </tr>
  <tr style='background:#f9f9f9'>
    <td style='padding:12px;border-bottom:1px solid #ddd'>Dashboard</td>
    <td style='padding:12px;border-bottom:1px solid #ddd'>24/7 Online</td>
    <td style='padding:12px;border-bottom:1px solid #ddd;color:#27ae60'><strong>LIVE</strong></td>
  </tr>
</table>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#e67e22'>CURRENT METRICS</h2>

<div style='background:#fff9e6;padding:15px;border-left:4px solid #e67e22;border-radius:4px;margin:15px 0'>
  <p><strong>Daily Change:</strong> <span style='color:#27ae60;font-size:18px'>+10.1%</span></p>
  <p><strong>Weekly Change:</strong> <span style='color:#d32f2f;font-size:18px'>-0.7%</span></p>
  <p><strong>Monthly Change:</strong> <span style='color:#27ae60;font-size:18px'>+3.6%</span></p>
  <p><strong>Yearly Change:</strong> <span style='color:#27ae60;font-size:18px'>+47.1%</span></p>
</div>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#1f77b4'>DASHBOARD FEATURES</h2>

<ul style='font-size:14px;line-height:1.8'>
  <li><strong>Sales Trends Tab:</strong> Daily, weekly, monthly, yearly metrics by ASIN</li>
  <li><strong>Review Ratings Tab:</strong> 8 tracked products with ratings and review counts</li>
  <li><strong>Data Tables:</strong> Raw sales history and review snapshots</li>
  <li><strong>Real-time Charts:</strong> See sales trends for each product individually</li>
  <li><strong>Auto-refresh:</strong> Updates every 5 minutes</li>
</ul>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#2ca02c'>KEY BENEFITS</h2>

<div style='display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:15px 0'>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>Cloud-Based</strong></p>
    <p style='font-size:13px;color:#555'>No PC needed, accessible 24/7 from anywhere</p>
  </div>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>Automated</strong></p>
    <p style='font-size:13px;color:#555'>Runs on schedule, no manual work required</p>
  </div>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>Smart Alerts</strong></p>
    <p style='font-size:13px;color:#555'>Email notifications on 20%+ sales changes</p>
  </div>
  <div style='background:#e8f5e9;padding:12px;border-radius:4px'>
    <p><strong>By ASIN</strong></p>
    <p style='font-size:13px;color:#555'>Track performance of each product individually</p>
  </div>
</div>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<h2 style='color:#1f77b4'>READY TO USE</h2>

<p style='background:#f0f8ff;padding:15px;border-left:4px solid #1f77b4;border-radius:4px;margin:15px 0'>
  Everything is set up and running. Just visit the dashboard link above and start monitoring!
</p>

<hr style='border:none;border-top:2px solid #eee;margin:20px 0'>

<p style='color:#666;font-size:12px'>
  <strong>System Status:</strong> LIVE & OPERATIONAL<br>
  <strong>Dashboard:</strong> https://usplusdashboardmonitoring.streamlit.app/<br>
  <strong>Monitoring:</strong> 24/7 Automated<br>
  <strong>Launched:</strong> """ + datetime.now().strftime('%B %d, %Y at %I:%M %p') + """
</p>

</body></html>
"""

# Send CORRECTED announcement with the RIGHT URL
send_alert(
    subject="LIVE: US+ Health Amazon Monitoring Dashboard",
    body_html=announcement_html,
    recipients=["julian@usplushealth.com", "max@usplushealth.com"]
)

print("[SUCCESS] CORRECTED announcement sent with correct dashboard URL!")
print("\nDashboard URL: https://usplusdashboardmonitoring.streamlit.app/")
