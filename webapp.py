#!/usr/bin/env python3
import base64
import hashlib
import os
import secrets
import time

import requests
from flask import Flask, Response, jsonify, render_template, request
from flask_login import (
    LoginManager, UserMixin, current_user, login_required, login_user, logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import storage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv(os.path.join(BASE_DIR, ".env"))
db.init_db()

WIDTH, HEIGHT = 1200, 1200
CF_TEXT_TO_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
CF_TRANSLATE_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8"
TRANSLATE_SYSTEM_PROMPT = (
    "You translate Italian image-generation prompts into vivid, literal English "
    "suitable for an AI image generator. Translate the MEANING and IMAGERY, not "
    "word-for-word. If the source uses an idiom or figure of speech, describe what "
    "it would actually look like visually instead of translating it literally. "
    "Reply with ONLY the English translation, nothing else."
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

login_manager = LoginManager()
login_manager.init_app(app)


@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"error": "Devi accedere per usare questa funzione."}), 401


class User(UserMixin):
    def __init__(self, row):
        self.id = str(row["id"])
        self.username = row["username"]


@login_manager.user_loader
def load_user(user_id):
    row = db.get_user_by_id(int(user_id))
    return User(row) if row else None


def cf_credentials():
    return os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")


def cf_not_configured_response():
    return jsonify({
        "error": "Cloudflare Workers AI non configurato: crea un file .env con "
                 "CF_ACCOUNT_ID e CF_API_TOKEN nella cartella del progetto, poi riavvia il server."
    }), 500


def cf_run(model, **request_kwargs):
    """POST to a Cloudflare Workers AI model. Returns (payload_dict, error_response_or_None)."""
    account_id, api_token = cf_credentials()
    if not account_id or not api_token:
        return None, cf_not_configured_response()

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {api_token}", **request_kwargs.pop("headers", {})}
    try:
        resp = requests.post(url, headers=headers, timeout=60, **request_kwargs)
    except requests.RequestException as e:
        return None, (jsonify({"error": f"Errore di rete verso Cloudflare: {e}"}), 502)

    if resp.status_code != 200:
        return None, (jsonify({"error": f"Cloudflare ha risposto {resp.status_code}: {resp.text[:300]}"}), 502)

    payload = resp.json()
    if not payload.get("success"):
        return None, (jsonify({"error": f"Errore Cloudflare: {payload.get('errors')}"}), 502)

    return payload, None


def translate_to_english(text):
    """Best-effort IT->EN translation via an instruction-following LLM, which handles
    idioms and long/complex sentences far better than a dedicated MT model. Falls back
    to the original text on any failure."""
    payload, err = cf_run(CF_TRANSLATE_MODEL, json={
        "messages": [
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    })
    if err:
        return text
    return payload["result"]["response"].strip()


def seed_from(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (10**6)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 3:
        return jsonify({"error": "Lo username deve avere almeno 3 caratteri."}), 400
    if len(password) < 6:
        return jsonify({"error": "La password deve avere almeno 6 caratteri."}), 400
    if db.get_user_by_username(username):
        return jsonify({"error": "Username già in uso."}), 400

    user_id = db.create_user(username, generate_password_hash(password, method="pbkdf2:sha256"))
    login_user(User(db.get_user_by_id(user_id)), remember=True)
    return jsonify({"username": username})


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    row = db.get_user_by_username(username)
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Username o password non corretti."}), 401

    login_user(User(row), remember=True)
    return jsonify({"username": row["username"]})


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/me")
def me():
    if current_user.is_authenticated:
        return jsonify({"username": current_user.username})
    return jsonify({"username": None})


@app.route("/history")
@login_required
def history():
    rows = db.get_user_images(int(current_user.id))
    return jsonify({
        "images": [
            {
                "prompt": r["prompt"],
                "seed": r["seed"],
                "image_url": f"/output/{r['filename']}",
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    })


@app.route("/cf/text-to-image", methods=["POST"])
def cf_text_to_image():
    data = request.get_json(force=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Il prompt non può essere vuoto."}), 400

    english_prompt = translate_to_english(prompt)

    payload, err = cf_run(CF_TEXT_TO_IMAGE_MODEL, json={"prompt": english_prompt})
    if err:
        return err

    image_bytes = base64.b64decode(payload["result"]["image"])
    seed = seed_from(prompt)
    filename = f"cf_{seed}_{int(time.time())}.png"
    storage.put(filename, image_bytes)

    if current_user.is_authenticated:
        db.save_image(int(current_user.id), prompt, seed, filename)

    return jsonify({
        "image_url": f"/output/{filename}",
        "params": {
            "seed": seed,
            "source": f"cloudflare-workers-ai ({CF_TEXT_TO_IMAGE_MODEL})",
            "translated_prompt": english_prompt if english_prompt.strip().lower() != prompt.strip().lower() else None,
        },
    })


@app.route("/output/<path:filename>")
def output_file(filename):
    data = storage.get(filename)
    if data is None:
        return jsonify({"error": "Immagine non trovata."}), 404
    return Response(data, mimetype="image/png")


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=debug, host="0.0.0.0", port=port)
