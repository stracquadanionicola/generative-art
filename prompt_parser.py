"""Traduce un prompt testuale libero in parametri per generate.build_image.

Non è comprensione del linguaggio: è un matching per parole chiave
(colore/mood/stile) su un dizionario italiano+inglese. Stessa frase ->
stesso seed -> stessa immagine (riproducibile).
"""
import hashlib

PALETTE_KEYWORDS = {
    "sunset": ["tramonto", "sunset", "crepuscolo", "arancione", "rosa", "pesca", "aurora"],
    "ocean": ["oceano", "mare", "acqua", "blu", "azzurro", "onda", "onde", "ocean", "abisso"],
    "forest": ["foresta", "bosco", "verde", "natura", "muschio", "smeraldo", "giungla"],
    "neon": ["neon", "cyber", "cyberpunk", "elettrico", "futuristico", "sintetico", "vaporwave", "elettro"],
    "fire": ["fuoco", "fiamma", "fiamme", "rosso", "lava", "vulcano", "incendio", "caldo", "brace"],
}
DEFAULT_PALETTE = "sunset"

INTENSITY_KEYWORDS = {
    "low": ["calmo", "calma", "minimale", "delicato", "sereno", "soft", "leggero", "quieto", "semplice"],
    "high": ["caotico", "caos", "esplosivo", "intenso", "energico", "turbolento", "denso", "selvaggio", "frenetico"],
}

FLOW_KEYWORDS = {
    "smooth": ["fluido", "morbido", "liscio", "sinuoso", "elegante", "lento"],
    "jagged": ["frastagliato", "nervoso", "spigoloso", "frammentato", "spezzato", "veloce"],
}


def _score(text, keyword_groups):
    return {name: sum(1 for kw in words if kw in text) for name, words in keyword_groups.items()}


def parse_prompt(prompt: str) -> dict:
    text = prompt.lower()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    h = int(digest, 16)

    # ogni prompt genera sempre variazione visibile, anche senza parole chiave
    # riconosciute: i valori "jitter_*" derivano dall'hash del testo stesso.
    palette_names = list(PALETTE_KEYWORDS)
    jitter_particles = h % 500
    jitter_octaves = (h // 500) % 3
    jitter_step = ((h // 1500) % 100) / 100 * 1.5

    palette_scores = _score(text, PALETTE_KEYWORDS)
    best_palette = max(palette_scores, key=palette_scores.get)
    if palette_scores[best_palette] > 0:
        palette = best_palette
    else:
        palette = palette_names[h % len(palette_names)]

    intensity = _score(text, INTENSITY_KEYWORDS)
    if intensity["high"] > intensity["low"]:
        particles, octaves = 2200 + jitter_particles, 6 + jitter_octaves
    elif intensity["low"] > intensity["high"]:
        particles, octaves = 500 + jitter_particles, 3 + jitter_octaves
    else:
        particles, octaves = 900 + jitter_particles, 4 + jitter_octaves

    flow = _score(text, FLOW_KEYWORDS)
    if flow["smooth"] > flow["jagged"]:
        step_len = 2.5 + jitter_step
    elif flow["jagged"] > flow["smooth"]:
        step_len = 1.0 + jitter_step * 0.3
    else:
        step_len = 1.5 + jitter_step

    seed = h % (10**6)

    return {
        "palette": palette,
        "particles": particles,
        "steps": 350,
        "step_len": round(step_len, 2),
        "octaves": octaves,
        "seed": seed,
    }
