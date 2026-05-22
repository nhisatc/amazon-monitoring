import config
from junglescout import ClientSync
from junglescout.models.params import Marketplace

client = ClientSync(
    api_key_name=config.JUNGLE_SCOUT_API_KEY_NAME,
    api_key=config.JUNGLE_SCOUT_API_KEY,
    marketplace=Marketplace.US,
)

# Print all available methods on the client
methods = [m for m in dir(client) if not m.startswith("_")]
print("Available methods:")
for m in methods:
    print(f"  {m}")
