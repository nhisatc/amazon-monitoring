import os
import certifi
from dotenv import load_dotenv

# Fix SSL certificate verification on Windows
os.environ["SSL_CERT_FILE"]      = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
SSL_VERIFY = certifi.where()

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

SP_API_CREDENTIALS = {
    "lwa_app_id":      os.environ["LWA_APP_ID"],
    "lwa_client_secret": os.environ["LWA_CLIENT_SECRET"],
    "refresh_token":   os.environ["SP_API_REFRESH_TOKEN"],
}
SELLER_ID      = os.environ["SELLER_ID"]
MARKETPLACE_ID = os.environ.get("MARKETPLACE_ID", "ATVPDKIKX0DER")

GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_RECIPIENTS   = [r.strip() for r in os.environ["ALERT_RECIPIENTS"].split(",")]

JUNGLE_SCOUT_API_KEY_NAME = os.environ["JUNGLE_SCOUT_API_KEY_NAME"]
JUNGLE_SCOUT_API_KEY      = os.environ["JUNGLE_SCOUT_API_KEY"]

SALES_THRESHOLD = 0.20   # 20 % change triggers an alert
LOW_STAR_MAX    = 2      # alert on reviews with ≤ this rating

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
