import config, json, inspect
from junglescout import ClientSync
from junglescout.models.parameters.marketplace import Marketplace
from junglescout.models.responses import keyword_by_asin

# Print response structure
with open("js_kba_source.txt", "w", encoding="utf-8") as f:
    f.write(inspect.getsource(keyword_by_asin))

client = ClientSync(
    api_key_name=config.JUNGLE_SCOUT_API_KEY_NAME,
    api_key=config.JUNGLE_SCOUT_API_KEY,
    marketplace=Marketplace.US,
)

# Test keywords_by_asin for a few ASINs
for asin in ["B097HP7DQ6", "B0BR99MF15", "B09CV925V4"]:
    try:
        result = client.keywords_by_asin(asin=asin)
        if result and result.data:
            item = result.data[0]
            with open(f"js_kba_{asin}.json", "w", encoding="utf-8") as f:
                json.dump(vars(item) if hasattr(item, "__dict__") else str(item), f, indent=2, default=str)
            print(f"{asin}: {len(result.data)} keyword(s) — saved to js_kba_{asin}.json")
        else:
            print(f"{asin}: no data returned")
    except Exception as e:
        print(f"{asin}: error — {e}")
