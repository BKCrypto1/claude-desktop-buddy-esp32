#!/usr/bin/env python3
"""
Convert a Petdex spritesheet → Claude Buddy GIF character pack.

Petdex standard spritesheet: 1536×1872, 8 cols × 9 rows, 192×208 px/frame, ARGB WebP/PNG.

Row layout (standard Petdex order):
  0  Idle       6 frames
  1  Run Right  8 frames
  2  Run Left   8 frames
  3  Waving     4 frames
  4  Jumping    5 frames
  5  Failed     8 frames
  6  Waiting    6 frames
  7  Running    6 frames
  8  Review     6 frames

Buddy state mapping:
  sleep     ← Waiting   (row 6)
  idle      ← Idle      (row 0)
  busy      ← Running   (row 7)
  attention ← Failed    (row 5)
  celebrate ← Jumping   (row 4)
  dizzy     ← Review    (row 8)
  heart     ← Waving    (row 3)

Usage:
  python3 tools/petdex_convert.py ~/.codex/pets/mallow/spritesheet.webp \\
      --name mallow --bg 000000 --out characters/mallow
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile

FRAME_W = 192
FRAME_H = 208
OUT_W   = 96
OUT_H   = 104  # preserves 192:208 aspect ratio

ROWS = {
    "idle_src":  (0, 6),
    "run_right": (1, 8),
    "run_left":  (2, 8),
    "waving":    (3, 4),
    "jumping":   (4, 5),
    "failed":    (5, 8),
    "waiting":   (6, 6),
    "running":   (7, 6),
    "review":    (8, 6),
}

# buddy_state → (petdex_row_label, gif_delay_ms)
STATE_MAP = {
    "sleep":     ("waiting",   133),
    "idle":      ("idle_src",  100),
    "busy":      ("running",    80),
    "attention": ("failed",    100),
    "celebrate": ("jumping",   100),
    "dizzy":     ("review",    100),
    "heart":     ("waving",    120),
}


def extract_frames(sheet, row_idx, n_frames, bg_hex, tmp_dir, label, pixel_art=False):
    """Crop each frame, composite on bg, scale to OUT_W.

    pixel_art=True  — nearest-neighbour scaling, no RGB565 posterize.
                      Preserves crisp pixel boundaries on art designed at pixel scale.
    pixel_art=False — Lanczos scaling + RGB565 posterize.
                      Best for smooth/illustrated characters (default).
    """
    paths = []
    y = row_idx * FRAME_H
    for i in range(n_frames):
        x = i * FRAME_W
        out = os.path.join(tmp_dir, f"{label}_{i:03d}.png")
        cmd = ["magick", sheet,
               "-crop", f"{FRAME_W}x{FRAME_H}+{x}+{y}", "+repage"]
        if pixel_art:
            # Point filter = nearest-neighbour: keeps every pixel edge crisp.
            cmd += ["-filter", "point", "-resize", f"{OUT_W}x{OUT_H}!"]
        else:
            cmd += ["-resize", f"{OUT_W}x{OUT_H}!"]
        cmd += ["-background", f"#{bg_hex}", "-flatten"]
        if not pixel_art:
            # Snap to RGB565 colour space so GIF palette entries map cleanly
            # to the 16-bit canvas without double-quantisation noise.
            cmd += ["-channel", "R", "-posterize", "32",
                    "-channel", "G", "-posterize", "64",
                    "-channel", "B", "-posterize", "32",
                    "+channel"]
        cmd.append(out)
        subprocess.run(cmd, check=True, capture_output=True)
        paths.append(out)
    return paths


def make_gif(frame_paths, delay_ms, out_path, pixel_art=False):
    """Combine frames into an animated GIF without dithering."""
    delay_centisec = max(1, delay_ms // 10)
    tmp_palette = out_path.replace(".gif", "_palette.png")

    # Pixel art uses a small, exact palette — 64 colours is plenty and keeps
    # each entry faithful to the source.  Illustrated characters need 256 to
    # cover their gradient range after RGB565 snapping.
    n_colors = "64" if pixel_art else "256"
    subprocess.run(
        ["magick"] + frame_paths + ["+append", "-colors", n_colors, "-unique-colors", tmp_palette],
        check=True, capture_output=True,
    )

    args = ["magick", "-delay", str(delay_centisec), "-loop", "0"]
    args += frame_paths
    # No -layers Optimize: firmware expects full-frame GIFs. Delta/sub-rect
    # frames mark unchanged pixels transparent; the renderer replaces transparent
    # with bg color instead of keeping the previous frame → corruption.
    args += ["-dither", "None", "-remap", tmp_palette, out_path]
    subprocess.run(args, check=True, capture_output=True)
    os.unlink(tmp_palette)

    # --lossy shrinks files without creating delta frames (no --optimize flag).
    if shutil.which("gifsicle"):
        subprocess.run(
            ["gifsicle", "--batch", "--lossy=80", out_path],
            capture_output=True,
        )


def main():
    parser = argparse.ArgumentParser(description="Petdex → Claude Buddy character converter")
    parser.add_argument("sheet", help="Path to spritesheet.webp or .png")
    parser.add_argument("--name", default="pet", help="Character name (default: pet)")
    parser.add_argument("--bg",   default="000000", help="Background hex colour, no # (default: 000000)")
    parser.add_argument("--body", default="808080", help="Body colour for manifest (default: 808080)")
    parser.add_argument("--text", default="ffffff", help="Text colour for manifest (default: ffffff)")
    parser.add_argument("--out",       default=None, help="Output directory (default: characters/<name>)")
    parser.add_argument("--pixel-art", action="store_true",
                        help="Nearest-neighbour scaling + exact palette (best for pixel-art characters)")
    args = parser.parse_args()
    pixel_art = args.pixel_art

    out_dir = args.out or os.path.join("characters", args.name)
    os.makedirs(out_dir, exist_ok=True)

    mode = "pixel-art (nearest-neighbour)" if pixel_art else "illustrated (Lanczos + RGB565 snap)"
    print(f"  mode: {mode}")

    with tempfile.TemporaryDirectory() as tmp:
        for buddy_state, (row_label, delay_ms) in STATE_MAP.items():
            row_idx, n_frames = ROWS[row_label]
            print(f"  {buddy_state:12s} ← {row_label} (row {row_idx}, {n_frames} frames, {delay_ms}ms)")
            frames = extract_frames(args.sheet, row_idx, n_frames, args.bg, tmp, buddy_state, pixel_art)
            gif_path = os.path.join(out_dir, f"{buddy_state}.gif")
            make_gif(frames, delay_ms, gif_path, pixel_art)
            size_kb = os.path.getsize(gif_path) / 1024
            print(f"    → {gif_path}  ({size_kb:.1f} KB)")

    # Generate manifest.json
    manifest = {
        "name": args.name,
        "colors": {
            "body":    f"#{args.body}",
            "bg":      f"#{args.bg}",
            "text":    f"#{args.text}",
            "textDim": "#808080",
            "ink":     "#000000",
        },
        "states": {state: f"{state}.gif" for state in STATE_MAP},
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    total_kb = sum(
        os.path.getsize(os.path.join(out_dir, f)) / 1024
        for f in os.listdir(out_dir)
    )
    print(f"\nDone. {out_dir}/  ({total_kb:.0f} KB total)")
    print("Load via sim_driver.py → 'Upload character' or:")
    print(f"  python3 tools/flash_character.py {out_dir}")


if __name__ == "__main__":
    main()
