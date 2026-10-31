#!/usr/bin/env python3
# Author: Tim Harrison
# Created: 2026-10-09
# Updated: 2026-10-23

"""Import the game's own minimaps into PopTracker's user-override directory.

The pack ships flat placeholder backgrounds; PopTracker reads a pack's files
from `user-override/<package_uid>/` first (pack.cpp:239), so dropping the real
minimaps there upgrades every level map with no pack change and no game art in
the repo. Those textures are (c) Activision and are extracted from the player's
own install for personal use — they are never committed (see README).

The game stores one minimap per level as `UI_MiniMap_<n>` where `<n>` is the
level's `LS<n>` number (world/data/client.json levelPaths), so each maps 1:1 to
a generated map name (`<game>_<slug>`). Textures are uncompressed
PF_B8G8R8A8 (raw BGRA), so decoding needs no UE4 texture codec.

Needs `repak` (https://github.com/trumank/repak) on PATH or under
~/.cargo/git/checkouts/repak-*/**/target/release/repak, and Pillow.

Run from anywhere:
    python3 <repo>/poptracker-pack/import_maps.py [--game 1|2|3|all]
        [--paks DIR] [--repak PATH] [--dest DIR] [--keep-alpha] [--dry-run]
"""
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys

from cli import game_parser

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLIENT_JSON = os.path.join(REPO, "world", "data", "client.json")
PACKAGE_UID = "spyro_reignited_ap"
ASSET_DIR = "Falcon/Plugins/UserInterface/Content/Textures/MiniMap"
STEAM_PAKS = os.path.join(
    os.path.expanduser("~"), ".local", "share", "Steam", "steamapps", "common",
    "Spyro Reignited Trilogy", "Falcon", "Content", "Paks")
GAMES = ("spyro1", "spyro2", "spyro3")
BG_RGB = (0x1c, 0x24, 0x31)  # matches the generated placeholder background


def find_repak(explicit):
    """The repak executable: explicit, PATH, or the cargo checkout docs use."""
    if explicit:
        return explicit
    found = shutil.which("repak")
    if found:
        return found
    for path in glob.glob(os.path.expanduser(
            "~/.cargo/git/checkouts/repak-*/**/target/release/repak"),
            recursive=True):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def find_paks(explicit):
    if explicit:
        return explicit
    return STEAM_PAKS if os.path.isdir(STEAM_PAKS) else None


def slug(name):
    """Level-name slug, identical to gen_pack.map_name's, so filenames match."""
    return "".join(c for c in name if c.isalnum())


def map_name(game, region):
    return f"{game}_{slug(region)}"


def levels(game):
    """[(minimap number, generated map name), ...] for one game, in order.
    The number comes from the level's `LS<n>` path; the name from its region."""
    with open(CLIENT_JSON, encoding="utf-8-sig") as f:
        paths = json.load(f)["levelPaths"][game]
    out = []
    seen = set()
    for path, region in paths.items():
        match = re.search(r"/LS(\d+)_", path)
        if not match:
            sys.exit(f"ERROR: {game} path {path!r} has no LS number")
        name = map_name(game, region)
        if name in seen:
            continue
        seen.add(name)
        out.append((int(match.group(1)), name))
    return out


def get_asset(repak, paks, member):
    """Read a member from whichever pak holds it (repak prints a warning and
    exits nonzero when it is missing)."""
    for pak in sorted(glob.glob(os.path.join(paks, "*.pak"))):
        proc = subprocess.run([repak, "get", pak, member],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              check=False)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    return None


def decode_bgra(uexp, keep_alpha):
    """A UTexture2D .uexp of raw PF_B8G8R8A8 mip data -> PNG bytes. The header
    length is whatever remains after the single square mip (UI textures are
    never mipmapped); verify the pixel count is a perfect square."""
    from io import BytesIO

    from PIL import Image

    n = len(uexp)
    size = None
    for header in range(128, 2048):
        pixels = n - header
        if pixels <= 0 or pixels % 4:
            continue
        w = math.isqrt(pixels // 4)
        if w >= 16 and w * w * 4 == pixels:
            size = w
            break
    if size is None:
        raise ValueError("could not locate a square BGRA mip")
    pixels = uexp[n - size * size * 4:]
    img = Image.frombuffer("RGBA", (size, size), pixels, "raw", "BGRA", 0, 1)
    if not keep_alpha:
        img = Image.alpha_composite(
            Image.new("RGBA", img.size, (*BG_RGB, 255)), img).convert("RGB")
    out = BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def main():
    ap = game_parser(__doc__.splitlines()[0])
    ap.add_argument("--paks", help="Falcon/Content/Paks directory")
    ap.add_argument("--repak", help="path to the repak executable")
    ap.add_argument("--dest", help="override package dir (default ~/PopTracker/"
                    f"user-override/{PACKAGE_UID})")
    ap.add_argument("--keep-alpha", action="store_true",
                    help="keep the texture alpha instead of compositing")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be written, extract nothing")
    args = ap.parse_args()

    repak = find_repak(args.repak)
    paks = find_paks(args.paks)
    if not repak:
        sys.exit("ERROR: repak not found — install it or pass --repak")
    if not paks:
        sys.exit("ERROR: game paks not found — pass --paks "
                 "(Falcon/Content/Paks)")
    dest_root = args.dest or os.path.join(
        os.path.expanduser("~"), "PopTracker", "user-override", PACKAGE_UID)
    out_dir = os.path.join(dest_root, "images", "maps")
    games = GAMES if args.game in ("all",) else (
        {"1": "spyro1", "2": "spyro2", "3": "spyro3"}.get(args.game, args.game))

    total = written = missing = 0
    for game in ([games] if isinstance(games, str) else games):
        for num, name in levels(game):
            total += 1
            member = f"{ASSET_DIR}/UI_MiniMap_{num}.uexp"
            target = os.path.join(out_dir, f"{name}.png")
            if args.dry_run:
                print(f"would write {target}  <-  {member}")
                continue
            uexp = get_asset(repak, paks, member)
            if not uexp:
                print(f"WARN: {member} not found in any pak")
                missing += 1
                continue
            os.makedirs(out_dir, exist_ok=True)
            with open(target, "wb") as f:
                f.write(decode_bgra(uexp, args.keep_alpha))
            written += 1
    if not args.dry_run:
        print(f"wrote {written}/{total} minimaps to {out_dir}"
              + (f" ({missing} missing in paks)" if missing else ""))
        print("Restart PopTracker to pick them up.")


if __name__ == "__main__":
    main()
