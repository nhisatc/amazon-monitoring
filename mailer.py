import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_RECIPIENTS

CC_RECIPIENTS = ["venus@ushealthplus.com"]


def send_alert(subject: str, body_html: str, recipients: list[str] = None):
    recipients = recipients or ALERT_RECIPIENTS
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = ", ".join(recipients)
    msg["Cc"]      = ", ".join(CC_RECIPIENTS)
    msg.attach(MIMEText(body_html, "html"))

    all_recipients = recipients + CC_RECIPIENTS
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, all_recipients, msg.as_string())
