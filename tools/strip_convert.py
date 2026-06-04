#!/usr/bin/env python3
"""
Convert a horizontal-strip sprite pack → Claude Buddy GIF character pack.

Each animation is a single PNG where frames are laid out left to right in one row.
Frame height = strip height. Frame width is auto-detected as the GCD of all
specified files' widths, or set explicitly with --frame-w.

Handles packs from itch.io and similar sources where each animation
lives in its own file (as opposed to Petdex's single spritesheet grid).

Usage:
  python3 tools/strip_convert.py /path/to/sprites/ \\
      --name mushroom --bg 000000 \\
      --idle   Mushroom-Idle.png \\
      --busy   Mushroom-Run.png \\
      --celebrate Mushroom-Attack.png \\
      --attention Mushroom-Hit.png \\
      --sleep  Mushroom-Stun.png \\
      --dizzy  Mushroom-Stun.png \\
      --heart  Mushroom-Idle.png
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile

STATES = ["sleep", "idle", "busy", "attention", "celebrate", "dizzy", "heart"]
STATE_DELAYS = {
    "sleep": 133, "idle": 100, "busy": 80,
    "attention": 100, "celebrate": 100, "dizzy": 100, "heart": 120,
}


def gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def sheet_dims(path):
    r = subprocess.run(
        ["magick", "identify", "-format", "%w %h", path],
        capture_output=True, text=True, check=True,
    )
    return tuple(map(int, r.stdout.strip().split()))


def detect_frame_w(paths, frame_h):
    """GCD of widths of all specified files; raises if any height mismatches."""
    widths = []
    for p in paths:
        w, h = sheet_dims(p)
        if h != frame_h:
            raise ValueError(f"{os.path.basename(p)}: height {h} != expected {frame_h}")
        widths.append(w)
    g = widths[0]
    for w in widths[1:]:
        g = gcd(g, w)
    return g


def extract_frames(sheet, frame_w, frame_h, bg_hex, tmp_dir, label, pixel_art=False):
    strip_w, _ = sheet_dims(sheet)
    n_frames = strip_w // frame_w
    paths = []
    for i in range(n_frames):
        x = i * frame_w
        out = os.path.join(tmp_dir, f"{label}_{i:03d}.png")
        cmd = ["magick", sheet,
               "-crop", f"{frame_w}x{frame_h}+{x}+0", "+repage"]
        if pixel_art:
            # Nearest-neighbour: preserves crisp pixel edges.
            cmd += ["-filter", "point", "-resize", "96x96"]
        else:
            # Fit within 96×96, preserving aspect ratio.
            cmd += ["-resize", "96x96"]
        cmd += ["-background", f"#{bg_hex}", "-flatten"]
        if not pixel_art:
            # Snap to RGB565 palette entries to reduce double-quantisation noise.
            cmd += ["-channel", "R", "-posterize", "32",
                    "-channel", "G", "-posterize", "64",
                    "-channel", "B", "-posterize", "32",
                    "+channel"]
        cmd.append(out)
        subprocess.run(cmd, check=True, capture_output=True)
        paths.append(out)
    return paths


def make_gif(frame_paths, delay_ms, out_path, pixel_art=False):
    delay_centisec = max(1, delay_ms // 10)
    tmp_palette = out_path.replace(".gif", "_palette.png")
    n_colors = "64" if pixel_art else "256"
    subprocess.run(
        ["magick"] + frame_paths + ["+append", "-colors", n_colors, "-unique-colors", tmp_palette],
        check=True, capture_output=True,
    )
    args = ["magick", "-delay", str(delay_centisec), "-loop", "0"]
    args += frame_paths
    # No -layers Optimize: firmware expects full-frame GIFs (see character.cpp).
    args += ["-dither", "None", "-remap", tmp_palette, out_path]
    subprocess.run(args, check=True, capture_output=True)
    os.unlink(tmp_palette)
    if shutil.which("gifsicle"):
        subprocess.run(["gifsicle", "--batch", "--lossy=80", out_path], capture_output=True)


def main():
    parser = argparse.ArgumentParser(
        description="Horizontal strip sprite pack → Claude Buddy character converter"
    )
    parser.add_argument("src_dir", help="Directory containing strip PNGs")
    parser.add_argument("--name",      default="character", help="Character name (default: character)")
    parser.add_argument("--bg",        default="000000",    help="Background hex colour, no # (default: 000000)")
    parser.add_argument("--body",      default="808080",    help="Body colour for manifest (default: 808080)")
    parser.add_argument("--text",      default="ffffff",    help="Text colour for manifest (default: ffffff)")
    parser.add_argument("--out",       default=None,        help="Output directory (default: characters/<name>)")
    parser.add_argument("--frame-w",   type=int, default=0,
                        help="Frame width in px (default: 0 = auto-detect from GCD of file widths)")
    parser.add_argument("--pixel-art", action="store_true",
                        help="Nearest-neighbour scaling + exact palette (best for pixel-art sprites)")
    for s in STATES:
        parser.add_argument(f"--{s}", default=None,
                            help=f"PNG filename (relative to src_dir) for the {s} state")
    args = parser.parse_args()
    pixel_art = args.pixel_art

    src_dir = os.path.abspath(args.src_dir)

    # Build state → absolute path mapping; missing states fall back to idle.
    state_files = {}
    for s in STATES:
        fn = getattr(args, s)
        if fn:
            state_files[s] = os.path.join(src_dir, fn)

    if not state_files:
        parser.error("No state files specified — use --idle, --busy, --celebrate, etc.")

    fallback = state_files.get("idle") or next(iter(state_files.values()))

    # Detect frame dimensions from the first specified file.
    first = next(iter(state_files.values()))
    _, frame_h = sheet_dims(first)

    frame_w = args.frame_w
    if frame_w == 0:
        frame_w = detect_frame_w(list(state_files.values()), frame_h)
        print(f"  auto frame-w: {frame_w}px")

    mode = "pixel-art (nearest-neighbour)" if pixel_art else "illustrated (Lanczos + RGB565 snap)"
    print(f"  frame: {frame_w}x{frame_h}  mode: {mode}")

    out_dir = args.out or os.path.join("characters", args.name)
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        for s in STATES:
            src = state_files.get(s, fallback)
            delay_ms = STATE_DELAYS[s]
            print(f"  {s:12s} ← {os.path.basename(src)}")
            frames = extract_frames(src, frame_w, frame_h, args.bg, tmp, s, pixel_art)
            gif_path = os.path.join(out_dir, f"{s}.gif")
            make_gif(frames, delay_ms, gif_path, pixel_art)
            size_kb = os.path.getsize(gif_path) / 1024
            print(f"    → {gif_path}  ({size_kb:.1f} KB)")

    manifest = {
        "name": args.name,
        "colors": {
            "body":    f"#{args.body}",
            "bg":      f"#{args.bg}",
            "text":    f"#{args.text}",
            "textDim": "#808080",
            "ink":     "#000000",
        },
        "states": {s: f"{s}.gif" for s in STATES},
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    total_kb = sum(
        os.path.getsize(os.path.join(out_dir, fn)) / 1024
        for fn in os.listdir(out_dir)
    )
    print(f"\nDone. {out_dir}/  ({total_kb:.0f} KB total)")
    print(f"  python3 tools/flash_character.py {out_dir}")


if __name__ == "__main__":
    main()
