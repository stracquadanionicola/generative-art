#!/usr/bin/env python3
import base64
import hashlib
import os
import time

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


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

WIDTH, HEIGHT = 1200, 1200
CF_TEXT_TO_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
CF_DESCRIBE_MODEL = "@cf/llava-hf/llava-1.5-7b-hf"
CF_DETECT_MODEL = "@cf/facebook/detr-resnet-50"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB upload limit


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


def seed_from(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (10**6)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/cf/text-to-image", methods=["POST"])
def cf_text_to_image():
    data = request.get_json(force=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Il prompt non può essere vuoto."}), 400

    payload, err = cf_run(CF_TEXT_TO_IMAGE_MODEL, json={"prompt": prompt})
    if err:
        return err

    image_bytes = base64.b64decode(payload["result"]["image"])
    seed = seed_from(prompt)
    filename = f"cf_{seed}_{int(time.time())}.png"
    with open(os.path.join(OUTPUT_DIR, filename), "wb") as f:
        f.write(image_bytes)

    return jsonify({
        "image_url": f"/output/{filename}",
        "params": {"seed": seed, "source": f"cloudflare-workers-ai ({CF_TEXT_TO_IMAGE_MODEL})"},
    })


@app.route("/cf/describe", methods=["POST"])
def cf_describe():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "Nessuna immagine caricata."}), 400

    payload, err = cf_run(CF_DESCRIBE_MODEL, data=file.read(), headers={"Content-Type": "application/octet-stream"})
    if err:
        return err

    return jsonify({"description": payload["result"]["description"].strip()})


@app.route("/cf/detect", methods=["POST"])
def cf_detect():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "Nessuna immagine caricata."}), 400

    payload, err = cf_run(CF_DETECT_MODEL, data=file.read(), headers={"Content-Type": "application/octet-stream"})
    if err:
        return err

    return jsonify({"objects": payload["result"]})


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=debug, host="0.0.0.0", port=port)
