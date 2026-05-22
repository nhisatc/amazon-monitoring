import config, httpx

headers = {
    "Authorization": f"JungleScout {config.JUNGLE_SCOUT_API_KEY_NAME}:{config.JUNGLE_SCOUT_API_KEY}",
    "X-Api-Type": "junglescout",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

endpoints = [
    ("GET",  "https://developer.junglescout.com/api/listing_analyzer"),
    ("GET",  "https://developer.junglescout.com/api/listing_analysis"),
    ("GET",  "https://developer.junglescout.com/api/listings"),
    ("GET",  "https://developer.junglescout.com/api/product_details"),
    ("GET",  "https://developer.junglescout.com/api/products"),
    ("POST", "https://developer.junglescout.com/api/listing_analyzer"),
    ("POST", "https://developer.junglescout.com/api/listing_analysis"),
    ("POST", "https://developer.junglescout.com/api/product_database_query?marketplace=us"),
]

for method, url in endpoints:
    if method == "GET":
        r = httpx.get(url, headers=headers, verify=config.SSL_VERIFY, timeout=10)
    else:
        r = httpx.post(url, headers=headers, json={}, verify=config.SSL_VERIFY, timeout=10)
    print(f"{method} {url.split('/api/')[-1]} -> {r.status_code}: {r.text[:120]}")
