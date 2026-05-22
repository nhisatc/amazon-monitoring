import config, datetime, json, inspect
from junglescout import ClientSync
from junglescout.models.parameters.marketplace import Marketplace
from junglescout.models.responses.product_database import ProductDatabase

# Print product database response fields
src = inspect.getsource(ProductDatabase)
with open("js_product_db_source.txt", "w", encoding="utf-8") as f:
    f.write(src)
print("Source written to js_product_db_source.txt")

client = ClientSync(
    api_key_name=config.JUNGLE_SCOUT_API_KEY_NAME,
    api_key=config.JUNGLE_SCOUT_API_KEY,
    marketplace=Marketplace.US,
)

test_asins = ["B0BR99MF15", "B097HP7DQ6"]

print("\nTesting product_database...")
try:
    result = client.product_database(include_keywords=test_asins)
    if hasattr(result, 'data') and result.data:
        item = result.data[0]
        with open("js_product_result.json", "w", encoding="utf-8") as f:
            try:
                json.dump(vars(item), f, indent=2, default=str)
                print("Result written to js_product_result.json")
            except:
                f.write(str(item))
    else:
        print(f"No data: {result}")
except Exception as e:
    print(f"Error: {e}")
