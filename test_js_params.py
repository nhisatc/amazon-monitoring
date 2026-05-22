import inspect
from junglescout.models.requests.product_database_request import ProductDatabaseRequest
from junglescout.client_sync import ClientSync

with open("js_pdb_params.txt", "w", encoding="utf-8") as f:
    f.write(inspect.getsource(ProductDatabaseRequest))
    f.write("\n\n---CLIENT---\n\n")
    f.write(inspect.getsource(ClientSync.product_database))

print("Done — check js_pdb_params.txt")
