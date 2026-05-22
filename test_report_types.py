import config, time, datetime
import certifi, httpx

_orig = httpx.Client
class _C(_orig):
    def __init__(self, *a, **kw):
        kw.setdefault("verify", certifi.where())
        super().__init__(*a, **kw)
httpx.Client = _C

from sp_api.api import Reports
from sp_api.base import Marketplaces

api   = Reports(credentials=config.SP_API_CREDENTIALS, marketplace=Marketplaces.US, verify=config.SSL_VERIFY)
start = (datetime.date.today() - datetime.timedelta(days=7)).isoformat() + "T00:00:00Z"
end   = datetime.date.today().isoformat() + "T23:59:59Z"

report_types = [
    "GET_PRODUCT_REVIEWS",
    "GET_FLAT_FILE_PRODUCT_REVIEWS_DATA",
    "GET_PRODUCT_REVIEWS_DATA",
    "PRODUCT_REVIEWS",
    "GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT",
    "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT",
    "GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT",
]

for rt in report_types:
    try:
        r = api.create_report(reportType=rt, dataStartTime=start, dataEndTime=end)
        rid = r.payload.get("reportId", "?")
        print(f"OK  {rt} -> reportId={rid}")
    except Exception as e:
        print(f"ERR {rt} -> {str(e)[:100]}")
    time.sleep(3)
