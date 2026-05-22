import config, time, gzip, csv, httpx, certifi
from io import StringIO

_orig = httpx.Client
class _C(_orig):
    def __init__(self, *a, **kw):
        kw.setdefault("verify", certifi.where())
        super().__init__(*a, **kw)
httpx.Client = _C

from sp_api.api import Reports
from sp_api.base import Marketplaces

api = Reports(credentials=config.SP_API_CREDENTIALS, marketplace=Marketplaces.US, verify=config.SSL_VERIFY)

print("Fetching active listings...")
resp = api.create_report(reportType="GET_MERCHANT_LISTINGS_DATA")
report_id = resp.payload["reportId"]

for _ in range(30):
    time.sleep(10)
    status = api.get_report(report_id).payload
    if status["processingStatus"] == "DONE":
        break
    if status["processingStatus"] in ("FATAL", "CANCELLED"):
        print(f"Report ended: {status['processingStatus']}")
        exit()

doc     = api.get_report_document(status["reportDocumentId"])
payload = doc.payload
resp    = httpx.get(payload["url"], verify=certifi.where(), timeout=60)
raw     = resp.content
if payload.get("compressionAlgorithm", "").upper() == "GZIP":
    raw = gzip.decompress(raw)

text   = raw.decode("utf-8")
reader = csv.DictReader(StringIO(text), delimiter="\t")
asins  = []
for row in reader:
    asin = row.get("asin1") or row.get("ASIN") or row.get("asin")
    if asin:
        asins.append(asin.strip())

print(f"\nFound {len(asins)} ASINs:")
for a in asins:
    print(f"  {a}")
