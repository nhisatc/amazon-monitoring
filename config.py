import os
import certifi
from dotenv import load_dotenv

# Fix SSL certificate verification on Windows
os.environ["SSL_CERT_FILE"]      = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
SSL_VERIFY = certifi.where()

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

SP_API_CREDENTIALS = {
    "lwa_app_id":      os.environ.get("LWA_APP_ID"),
    "lwa_client_secret": os.environ.get("LWA_CLIENT_SECRET"),
    "refresh_token":   os.environ.get("SP_API_REFRESH_TOKEN"),
}
SELLER_ID      = os.environ.get("SELLER_ID")
MARKETPLACE_ID = os.environ.get("MARKETPLACE_ID", "ATVPDKIKX0DER")

GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_RECIPIENTS   = [r.strip() for r in os.environ["ALERT_RECIPIENTS"].split(",")]

JUNGLE_SCOUT_API_KEY_NAME = os.environ["JUNGLE_SCOUT_API_KEY_NAME"]
JUNGLE_SCOUT_API_KEY      = os.environ["JUNGLE_SCOUT_API_KEY"]

ASIN_NAMES = {
    # Active listings
    "B08Y7X8375": "Hydrogen Peroxide 3% 32oz",
    "B08Y83DNZ5": "Hydrogen Peroxide 3% 1 Gal",
    "B097HP7DQ6": "Castor Oil 1 Gal",
    "B097LTHS4S": "Vegetable Glycerin 32oz",
    "B097LVPKMP": "Vegetable Glycerin 8oz",
    "B0981HX5NG": "Mineral Oil 8oz",
    "B09CV925V4": "Castor Oil 10oz",
    "B09DZ2P2WJ": "Sweet Almond Oil 1 Gal",
    "B09DZDD71G": "Sweet Almond Oil 10oz",
    "B0BJH3RD1F": "Mineral Oil 32oz",
    "B0BR99MF15": "Vegetable Glycerin 1 Gal",
    "B0CCMHLX72": "Castor Oil 20oz",
    "B0DDWQ1515": "Organic Castor Oil 16oz",
    "B0DSCKXPQH": "Organic Jojoba Oil 16oz",
    # Deleted / inactive listings (still appear in historical data)
    "B09DZ4FW8S": "Sweet Almond Oil (Deleted)",
    "B09DZ64Q5G": "Sweet Almond Oil (Deleted)",
    "B09DZ6X29K": "Sweet Almond Oil (Deleted)",
    "B0BR9931H4": "Vegetable Glycerin (Deleted)",
    "B0BR9BJQK5": "Vegetable Glycerin (Deleted)",
}

SALES_THRESHOLD = 0.20   # 20 % change triggers an alert
LOW_STAR_MAX    = 2      # alert on reviews with <= this rating

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
