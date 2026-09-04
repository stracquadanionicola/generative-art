import os

import requests

R2_BUCKET = "generative-art-images"


def _objects_url(filename=""):
    account_id = os.environ.get("CF_ACCOUNT_ID")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{R2_BUCKET}/objects"
    return f"{url}/{filename}" if filename else url


def _headers(extra=None):
    token = os.environ.get("CF_API_TOKEN")
    return {"Authorization": f"Bearer {token}", **(extra or {})}


def put(filename, data, content_type="image/png"):
    resp = requests.put(
        _objects_url(filename),
        headers=_headers({"Content-Type": content_type}),
        data=data,
        timeout=30,
    )
    resp.raise_for_status()


def get(filename):
    resp = requests.get(_objects_url(filename), headers=_headers(), timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content
