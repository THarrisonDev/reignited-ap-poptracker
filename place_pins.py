#!/usr/bin/env python3
# Author: Tim Harrison
# Created: 2026-10-09
# Updated: 2026-10-11

"""Locally place the pack's map pins on the real level maps.

The generator drops pins on a synthetic grid because nothing knows where a
check really is. This is a small local web tool to click each pin onto its
spot: serve the level map with the current grid pins overlaid, click, and save.
Saves go to `pin_coords.json`, which `gen_pack.py` reads to replace the grid
(see its PIN_COORDS). The file is local-only and gitignored — pin positions
derived from the game are treated like the map art (see README).

Maps: the tool serves whatever `<PACK>/images/maps/<map>.png` resolves to, so
run `import_maps.py` first to place pins on the real minimaps; without it you
place onto the flat placeholder.

Clicking:
  - left-click on empty space   places the selected (highlighted) check's pin
  - drag a pin                  moves it
  - right-click a pin           clears it back to the generated grid

Only a local server, no dependencies beyond the stdlib (Pillow only if you want
the map dimensions pre-checked). Run from anywhere:

    python3 <repo>/poptracker-pack/place_pins.py [--game 1|2|3|all] [--port N]

Then open http://127.0.0.1:<port>/ (defaults to 8765).
"""
import contextlib
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from cli import game_parser

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLIENT_JSON = os.path.join(REPO, "world", "data", "client.json")
PIN_COORDS = os.path.join(HERE, "pin_coords.json")
OVERRIDE = os.path.join(
    os.path.expanduser("~"), "PopTracker", "user-override",
    "spyro_reignited_ap", "images", "maps")
PACK_IMG = os.path.join(HERE, "images", "maps")
GAMES = ("spyro1", "spyro2", "spyro3")
PIN_START, PIN_STEP, PIN_COLS = 50, 50, 8


def slug(name):
    return "".join(c for c in name if c.isalnum())


def map_name(game, region):
    return f"{game}_{slug(region)}"


def grid_pin(i, count):
    cols = min(PIN_COLS, max(count, 1))
    return {"x": PIN_START + (i % cols) * PIN_STEP,
            "y": PIN_START + (i // cols) * PIN_STEP}


def load_locations():
    """{game: [{region, map, checks:[{name, section}], image, width, height}]}
    built from the generated locations, so the tool's pins match the pack 1:1."""
    from PIL import Image

    out = {}
    for game in GAMES:
        with open(os.path.join(HERE, "locations", f"{game}.json"),
                  encoding="utf-8-sig") as f:
            doc = json.load(f)
        regions = []
        for group in doc:
            mname = map_name(game, group["name"])
            # Only checks the generator gives a map pin (gems are per-level
            # percentages with no spot, so they are not placeable).
            checks = [{"name": c["name"],
                       "section": c["sections"][0]["name"]}
                      for c in group["children"] if "map_locations" in c]
            path = map_image_path(mname)
            width = height = 400
            if path:
                try:
                    width, height = Image.open(path).size
                except OSError:
                    pass
            regions.append({"region": group["name"], "map": mname,
                            "checks": checks, "image": _image_rel(mname),
                            "width": width, "height": height})
        out[game] = regions
    return out


def map_image_path(mname):
    """The map PNG the pack will actually show: user-override first, then the
    shipped placeholder (same precedence PopTracker uses)."""
    for base in (OVERRIDE, PACK_IMG):
        path = os.path.join(base, f"{mname}.png")
        if os.path.isfile(path):
            return path
    return None


def _image_rel(mname):
    which = "override" if os.path.isfile(
        os.path.join(OVERRIDE, f"{mname}.png")) else "pack"
    return f"/image/{which}/{mname}.png"


def load_coords():
    if not os.path.isfile(PIN_COORDS):
        return {}
    try:
        with open(PIN_COORDS, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_coords(data):
    tmp = PIN_COORDS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, PIN_COORDS)


PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Place pins</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font: 13px system-ui, sans-serif; background: #10151c;
         color: #dfe6ee; display: flex; height: 100vh; }
  #side { width: 300px; overflow: auto; border-right: 1px solid #2a3542;
          padding: 8px; box-sizing: border-box; }
  #side h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
             color: #8fa3b8; margin: 12px 0 4px; }
  .level { padding: 4px 6px; border-radius: 4px; cursor: pointer; }
  .level:hover { background: #1d2733; }
  .level.sel { background: #24405c; }
  .check { padding: 3px 6px; border-radius: 4px; cursor: pointer;
           display: flex; justify-content: space-between; gap: 8px; }
  .check:hover { background: #1d2733; }
  .check.sel { background: #2e6da4; }
  .check.done .tag { color: #4fd07a; }
  .check .tag { color: #ff7a7a; font-variant-numeric: tabular-nums; }
  #main { flex: 1; display: flex; flex-direction: column; }
  #bar { padding: 6px 10px; border-bottom: 1px solid #2a3542;
         display: flex; gap: 16px; align-items: center; }
  #bar b { color: #fff; }
  #stage { flex: 1; overflow: auto; display: grid; place-items: center; }
  #wrap { position: relative; }
  #map { display: block; image-rendering: pixelated; }
  .pin { position: absolute; width: 22px; height: 22px; margin: -11px 0 0 -11px;
         border: 2px solid #fff; box-sizing: border-box; border-radius: 3px;
         background: rgba(255,120,120,.35); cursor: grab; }
  .pin.set { background: rgba(80,220,120,.45); }
  .pin.sel { outline: 2px solid #ffd34d; }
  .pin span { position: absolute; inset: 0; font-size: 9px; line-height: 18px;
              text-align: center; color: #fff; pointer-events: none; }
  #hint { color: #8fa3b8; }
</style>
<div id="side"></div>
<div id="main">
  <div id="bar">
    <b id="title">&mdash;</b>
    <span id="hint">click empty space to place the selected check</span>
    <span id="count"></span>
  </div>
  <div id="stage"><div id="wrap"><img id="map"><div id="pins"></div></div></div>
</div>
<script>
const DATA = __DATA__;
const COORDS = __COORDS__;
let game = Object.keys(DATA)[0], level = 0, sel = 0;
const side = document.getElementById('side');

function mapCoords() {
  (COORDS[game] = COORDS[game] || {});
  const m = DATA[game][level].map;
  return (COORDS[game][m] = COORDS[game][m] || {});
}
function pinFor(i) {
  const c = mapCoords()[DATA[game][level].checks[i].section];
  return c || gridPin(i);
}
function gridPin(i) {
  const n = DATA[game][level].checks.length;
  const cols = Math.min(8, Math.max(n,1));
  return {x: 50 + (i % cols) * 50, y: 50 + Math.floor(i / cols) * 50};
}
function renderSide() {
  side.innerHTML = '';
  document.getElementById('title').textContent = game;
  for (const g of Object.keys(DATA)) {
    const h = document.createElement('h2'); h.textContent = g; side.appendChild(h);
    DATA[g].forEach((r, ri) => {
      const row = document.createElement('div');
      row.className = 'level' + (g===game && ri===level ? ' sel' : '');
      const done = Object.keys(COORDS[g] && COORDS[g][r.map] || {}).length;
      row.innerHTML = `<span>${r.region}</span> <span class="tag">${
        done}/${r.checks.length}</span>`;
      row.onclick = () => { game=g; level=ri; sel=0; render(); };
      side.appendChild(row);
      if (g===game && ri===level) renderChecks(r);
    });
  }
  document.getElementById('count').textContent =
    `${Object.keys(COORDS[game]&&COORDS[game][DATA[game][level].map]||{}).length}`+
    `/${DATA[game][level].checks.length} placed`;
}
function renderChecks(r) {
  r.checks.forEach((c, i) => {
    const e = document.createElement('div');
    const set = mapCoords()[c.section] ? ' done' : '';
    e.className = 'check' + (i===sel?' sel':'') + set;
    e.innerHTML = `<span>${c.section}</span> <span class="tag">${
      mapCoords()[c.section] ? '\\u2713' : ''}</span>`;
    e.onclick = () => { sel=i; render(); };
    side.appendChild(e);
  });
}
function renderMap() {
  const r = DATA[game][level];
  const img = document.getElementById('map');
  img.src = r.image;
  img.width = r.width; img.height = r.height;
  const pins = document.getElementById('pins');
  pins.innerHTML = '';
  r.checks.forEach((c, i) => {
    const p = pinFor(i);
    const e = document.createElement('div');
    e.className = 'pin' + (mapCoords()[c.section] ? ' set':'') + (i===sel?' sel':'');
    e.style.left = p.x + 'px'; e.style.top = p.y + 'px';
    e.innerHTML = `<span>${i+1}</span>`;
    e.onmousedown = ev => { sel=i; render(); drag(ev, i); };
    e.oncontextmenu = ev => {
      ev.preventDefault(); delete mapCoords()[c.section]; sel=i; render();
    };
    pins.appendChild(e);
  });
}
function drag(ev, i) {
  ev.preventDefault();
  const wrap = document.getElementById('wrap');
  const move = e => {
    const rect = wrap.getBoundingClientRect();
    const x = Math.round(e.clientX - rect.left);
    const y = Math.round(e.clientY - rect.top);
    mapCoords()[DATA[game][level].checks[i].section] = {x, y};
    renderMap(); renderSide();
  };
  const up = () => { window.removeEventListener('mousemove', move);
                     window.removeEventListener('mouseup', up); save(); };
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
}
document.getElementById('stage').onclick = ev => {
  if (ev.target.id !== 'map' && ev.target.id !== 'stage') return;
  const wrap = document.getElementById('wrap');
  const rect = wrap.getBoundingClientRect();
  const x = Math.round(ev.clientX - rect.left);
  const y = Math.round(ev.clientY - rect.top);
  mapCoords()[DATA[game][level].checks[sel].section] = {x, y};
  sel = Math.min(sel+1, DATA[game][level].checks.length-1);
  render(); save();
};
let saveT;
function save() {
  clearTimeout(saveT);
  saveT = setTimeout(() => {
    fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify(COORDS)});
  }, 250);
}
function render() { renderSide(); renderMap(); }
render();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    locations: ClassVar[dict] = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/plain"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = (PAGE.replace("__DATA__", json.dumps(self.locations))
                        .replace("__COORDS__", json.dumps(load_coords())))
            return self._send(200, page, "text/html; charset=utf-8")
        if self.path.startswith("/image/"):
            _, _, which, name = self.path.split("/", 3)
            base = OVERRIDE if which == "override" else PACK_IMG
            path = os.path.join(base, os.path.basename(name))
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return self._send(200, f.read(), "image/png")
            return self._send(404, "no image")
        return self._send(404, "not found")

    def do_POST(self):
        if self.path != "/save":
            return self._send(404, "not found")
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError as err:
            return self._send(400, f"bad json: {err}")
        if not isinstance(data, dict):
            return self._send(400, "expected a JSON object")
        save_coords(data)
        return self._send(200, "ok")


def main():
    ap = game_parser(__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    try:
        locations = load_locations()
    except ImportError:
        sys.exit("ERROR: Pillow is required (pip install Pillow)")
    if args.game not in ("all",):
        key = {"1": "spyro1", "2": "spyro2", "3": "spyro3"}.get(
            args.game, args.game)
        locations = {key: locations[key]}
    Handler.locations = locations
    overridden = sum(1 for g in locations for r in locations[g]
                     if r["image"].startswith("/image/override"))
    print(f"serving {sum(len(v) for v in locations.values())} levels "
          f"({overridden} with real map art)")
    if not overridden:
        print("note: no user-override maps found — run import_maps.py first "
              "to place pins on the real minimaps")
    addr = f"http://127.0.0.1:{args.port}/"
    print(f"open {addr}  (Ctrl-C to stop)")
    if not args.no_browser:
        with contextlib.suppress(OSError):
            webbrowser.open(addr)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
