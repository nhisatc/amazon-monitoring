"""
Look up when an order was placed, and how long the buyer kept it.

The gap between purchase and return is diagnostic: a unit returned within days
of arriving was probably wrong when it shipped, while one returned weeks later
points at degradation in the bottle or on the shelf. The returns report gives
only the return date, so this fills in the other half from the Orders API.
"""

import datetime as dt
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

ENDPOINT = "https://sellingpartnerapi-na.amazon.com"


def get_access_token() -> str:
    resp = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": os.environ["SP_API_REFRESH_TOKEN"],
            "client_id":     os.environ["LWA_APP_ID"],
            "client_secret": os.environ["LWA_CLIENT_SECRET"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_order(order_id: str, token: str) -> dict | None:
    """One order. Amazon throttles getOrder hard, so callers must pace themselves."""
    resp = requests.get(
        f"{ENDPOINT}/orders/v0/orders/{order_id}",
        headers={"x-amz-access-token": token},
        timeout=30,
    )
    if resp.status_code == 429:
        time.sleep(3)
        return get_order(order_id, token)
    if resp.status_code != 200:
        print(f"  {order_id}: HTTP {resp.status_code} {resp.text[:120]}")
        return None
    return resp.json().get("payload", {})


def lookup(order_ids: list[str]) -> dict[str, dict]:
    token = get_access_token()
    out = {}
    for i, order_id in enumerate(order_ids):
        payload = get_order(order_id, token)
        if payload:
            out[order_id] = {
                "purchase_date": payload.get("PurchaseDate", ""),
                "status":        payload.get("OrderStatus", ""),
                "total":         (payload.get("OrderTotal") or {}).get("Amount", ""),
                "ship_state":    (payload.get("ShippingAddress") or {}).get("StateOrRegion", ""),
            }
        time.sleep(2.2)          # stay under the getOrder rate limit
        if (i + 1) % 5 == 0:
            print(f"  …{i + 1}/{len(order_ids)}")
    return out


def days_between(purchase_iso: str, return_iso: str) -> int | None:
    try:
        p = dt.datetime.fromisoformat(purchase_iso.replace("Z", "+00:00"))
        r = dt.datetime.fromisoformat(return_iso.replace("Z", "+00:00"))
        return (r - p).days
    except Exception:
        return None


if __name__ == "__main__":
    ids = sys.argv[1:]
    if not ids:
        print("usage: python order_lookup.py <order-id> [<order-id> ...]")
        raise SystemExit(1)
    for order_id, info in lookup(ids).items():
        print(f"{order_id}")
        print(f"  ordered : {info['purchase_date']}")
        print(f"  status  : {info['status']}")
        print(f"  total   : {info['total']}")
        print(f"  ship-to : {info['ship_state']}")
