#!/usr/bin/env python3
"""Generatore di arte astratta generativa (flow field + rumore frattale).

Nessuna AI: tutto calcolato via codice (numpy + Pillow), zero costi per immagine.
"""
import argparse
import random

import numpy as np
from PIL import Image, ImageFilter

PALETTES = {
    "sunset": ["#0b0033", "#4a0072", "#ff6f3c", "#ffcd3c", "#ff3c78"],
    "ocean": ["#001220", "#003049", "#00798c", "#30e3ca", "#edf6f9"],
    "forest": ["#0b3d0b", "#1e5128", "#4e9f3d", "#d8e9a8", "#191a19"],
    "neon": ["#0d0221", "#0f4c81", "#e900ff", "#00fff0", "#f9f871"],
    "fire": ["#03071e", "#6a040f", "#d00000", "#faa307", "#ffba08"],
}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def make_palette_lut(colors, n=256):
    rgb = np.array([hex_to_rgb(c) for c in colors], dtype=float)
    stops = np.linspace(0, 1, len(colors))
    xs = np.linspace(0, 1, n)
    lut = np.zeros((n, 3))
    for c in range(3):
        lut[:, c] = np.interp(xs, stops, rgb[:, c])
    return lut


def fractal_value_noise(w, h, octaves, base_res, seed, persistence=0.5):
    rng = np.random.default_rng(seed)
    total = np.zeros((h, w))
    amp, amp_sum, res = 1.0, 0.0, base_res
    for _ in range(octaves):
        coarse = rng.uniform(0, 1, (res, res)).astype(np.float32)
        up = np.asarray(
            Image.fromarray((coarse * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC),
            dtype=np.float64,
        ) / 255.0
        total += amp * up
        amp_sum += amp
        amp *= persistence
        res *= 2
    return total / amp_sum


def simulate_flow_field(w, h, angle_field, n_particles, n_steps, step_len, palette_lut, seed):
    rng = np.random.default_rng(seed)
    canvas = np.zeros((h, w, 3), dtype=np.float64)
    xs = rng.uniform(0, w, n_particles)
    ys = rng.uniform(0, h, n_particles)
    colors = palette_lut[rng.uniform(0, 255, n_particles).astype(int)]
    alive = np.ones(n_particles, dtype=bool)

    for _ in range(n_steps):
        xi, yi = xs.astype(int), ys.astype(int)
        inb = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h) & alive
        alive &= inb
        if not alive.any():
            break
        idx = np.where(inb)[0]
        angles = angle_field[yi[idx], xi[idx]]
        canvas[yi[idx], xi[idx]] += colors[idx]
        xs[idx] += np.cos(angles) * step_len
        ys[idx] += np.sin(angles) * step_len

    return canvas


def render(canvas, bg_rgb, glow_scale=1.6, bloom_radius=6, bloom_strength=0.5):
    scale = np.percentile(canvas[canvas > 0], 92) * glow_scale
    accum = 1.0 - np.exp(-canvas / scale)
    bg = np.array(bg_rgb, dtype=float) / 255.0
    img = bg * (1 - accum.max(axis=2, keepdims=True)) + accum
    img = np.clip(img * 255, 0, 255).astype(np.uint8)
    base = Image.fromarray(img)

    bloom_src = np.clip(canvas / (canvas.max() + 1e-6) * 255, 0, 255).astype(np.uint8)
    bloom = Image.fromarray(bloom_src).filter(ImageFilter.GaussianBlur(bloom_radius))
    base_arr = np.asarray(base, dtype=float)
    bloom_arr = np.asarray(bloom, dtype=float)
    out = np.clip(base_arr + bloom_arr * bloom_strength, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


def build_image(width, height, palette, particles, steps, step_len, octaves, seed):
    noise = fractal_value_noise(width, height, octaves, base_res=4, seed=seed)
    angle_field = noise * 4 * np.pi

    palette_lut = make_palette_lut(PALETTES[palette])
    canvas = simulate_flow_field(
        width, height, angle_field, particles, steps, step_len, palette_lut, seed,
    )
    bg_rgb = hex_to_rgb(PALETTES[palette][0])
    return render(canvas, bg_rgb)


def main():
    p = argparse.ArgumentParser(description="Generatore di arte astratta generativa")
    p.add_argument("--width", type=int, default=1600)
    p.add_argument("--height", type=int, default=1600)
    p.add_argument("--palette", choices=list(PALETTES), default="sunset")
    p.add_argument("--particles", type=int, default=1200)
    p.add_argument("--steps", type=int, default=350)
    p.add_argument("--step-len", type=float, default=2.0)
    p.add_argument("--octaves", type=int, default=5)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", type=str, default="output/art.png")
    args = p.parse_args()

    seed = args.seed if args.seed is not None else random.randint(0, 10**6)
    print(f"seed={seed} palette={args.palette}")

    img = build_image(
        args.width, args.height, args.palette,
        args.particles, args.steps, args.step_len, args.octaves, seed,
    )
    img.save(args.out)
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
