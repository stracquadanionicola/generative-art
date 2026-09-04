import os
from datetime import datetime, timezone

import requests


def _query(sql, params=None):
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    database_id = os.environ.get("CF_D1_DATABASE_ID")

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_token}"},
        json={"sql": sql, "params": params or []},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"D1 query failed: {payload.get('errors')}")
    return payload["result"][0]


def init_db():
    _query("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    _query("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            seed INTEGER,
            filename TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


def create_user(username, password_hash):
    now = datetime.now(timezone.utc).isoformat()
    result = _query(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        [username, password_hash, now],
    )
    return result["meta"]["last_row_id"]


def get_user_by_username(username):
    rows = _query("SELECT * FROM users WHERE username = ?", [username])["results"]
    return rows[0] if rows else None


def get_user_by_id(user_id):
    rows = _query("SELECT * FROM users WHERE id = ?", [user_id])["results"]
    return rows[0] if rows else None


def save_image(user_id, prompt, seed, filename):
    now = datetime.now(timezone.utc).isoformat()
    _query(
        "INSERT INTO images (user_id, prompt, seed, filename, created_at) VALUES (?, ?, ?, ?, ?)",
        [user_id, prompt, seed, filename, now],
    )


def get_user_images(user_id, limit=24):
    return _query(
        "SELECT * FROM images WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        [user_id, limit],
    )["results"]
