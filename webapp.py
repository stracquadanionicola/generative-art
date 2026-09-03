#!/usr/bin/env python3
import base64
import hashlib
import os
import time
from urllib.parse import quote

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

from generate import build_image
from prompt_parser import parse_prompt

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
POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Il prompt non può essere vuoto."}), 400

    params = parse_prompt(prompt)
    img = build_image(
        WIDTH, HEIGHT, params["palette"],
        params["particles"], params["steps"], params["step_len"],
        params["octaves"], params["seed"],
    )

    filename = f"art_{params['seed']}_{int(time.time())}.png"
    img.save(os.path.join(OUTPUT_DIR, filename))

    return jsonify({"image_url": f"/output/{filename}", "params": params})


@app.route("/generate_ai", methods=["POST"])
def generate_ai():
    data = request.get_json(force=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Il prompt non può essere vuoto."}), 400

    seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), 16) % (10**6)
    image_url = (
        f"{POLLINATIONS_BASE}/{quote(prompt)}"
        f"?width={WIDTH}&height={HEIGHT}&seed={seed}&nologo=true"
    )

    return jsonify({"image_url": image_url, "params": {"seed": seed, "source": "pollinations.ai"}})


@app.route("/generate_cf", methods=["POST"])
def generate_cf():
    data = request.get_json(force=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Il prompt non può essere vuoto."}), 400

    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    if not account_id or not api_token:
        return jsonify({
            "error": "Cloudflare Workers AI non configurato: crea un file .env con "
                     "CF_ACCOUNT_ID e CF_API_TOKEN nella cartella del progetto, poi riavvia il server."
        }), 500

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{CF_MODEL}"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_token}"},
            json={"prompt": prompt},
            timeout=60,
        )
    except requests.RequestException as e:
        return jsonify({"error": f"Errore di rete verso Cloudflare: {e}"}), 502

    if resp.status_code != 200:
        return jsonify({"error": f"Cloudflare ha risposto {resp.status_code}: {resp.text[:300]}"}), 502

    payload = resp.json()
    if not payload.get("success"):
        return jsonify({"error": f"Errore Cloudflare: {payload.get('errors')}"}), 502

    image_bytes = base64.b64decode(payload["result"]["image"])

    seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), 16) % (10**6)
    filename = f"cf_{seed}_{int(time.time())}.png"
    with open(os.path.join(OUTPUT_DIR, filename), "wb") as f:
        f.write(image_bytes)

    return jsonify({
        "image_url": f"/output/{filename}",
        "params": {"seed": seed, "source": f"cloudflare-workers-ai ({CF_MODEL})"},
    })


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=debug, host="0.0.0.0", port=port)
