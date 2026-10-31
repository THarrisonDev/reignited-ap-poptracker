#!/usr/bin/env python3
# Author: Tim Harrison
# Created: 2026-10-09
# Updated: 2026-10-23

"""Generate the PopTracker pack's maps, locations and layouts.

Single source of truth: the repo's JSON data files, read through the world's
standalone data engine (world/data/__init__.py, stdlib-only — the same engine
the apworld and client/checkd/scripts/gen_locations.py load), so the pack,
the client and the apworld can never disagree on a location name or ID.

Outputs (checked in; regenerate after editing any source):
  - items/items.json                  tracker items (counters, keys, toggles)
  - maps/maps.json                    one trivial map per level/region
  - locations/spyro{1,2,3}.json       one group per level/region, one child
                                      per check with a grid map_locations pin
  - layouts/layouts.json              nested-tab view: game tabs ->
                                      Overview + one tab per level/region
  - scripts/spyro_locmap.lua          AP location id -> "@Location/Section"
                                      for autotracking.lua
  - scripts/spyro_itemmap.lua         AP item id -> {"code", "count", "trap"}
                                      for autotracking.lua

View shape (no map art): each level tab is a type-"map" layout backed by a
trivial map (placeholder background, computed grid pins), which keeps real AP
locations, sections and tooltips.

Run from anywhere:
    python3 <repo>/poptracker-pack/gen_pack.py [--check]
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "world", "data")

GAMES = ("spyro1", "spyro2", "spyro3")
PREFIX = {"spyro1": "Spyro 1: ", "spyro2": "Spyro 2: ", "spyro3": "Spyro 3: "}
TITLES = {"spyro1": "Spyro 1", "spyro2": "Spyro 2", "spyro3": "Spyro 3"}
# Overview counter rows per game. Counter codes come from items/items.json;
# the spyro2/3 rows end with the three ability / Sparx-power toggles that game
# can grant (spyro2 rows share the s2_* slots; spyro3 rows reuse the sparx_*
# toggles), so the Overview shows which movement powers are already active.
OVERVIEW_ROWS = {
    "spyro1": [["dragons", "spyro1_eggs", "s1_keys"]],
    "spyro2": [["orbs", "talismans", "s2_keys",
                "s2_swim", "s2_climb", "s2_headbash"]],
    "spyro3": [["eggs", "s3_keys",
                "sparx_gemcollectrange", "sparx_extrahitpoint",
                "sparx_chestbreaking"]],
}
HEADER_ROWS = [
    ["spyro1_played", "spyro2_played", "spyro3_played"],
    ["dragons", "orbs", "eggs"],
]
# Boss-event LOCATION ids (the slot's goal_location candidates) -> event ITEM
# name. Spliced into build_goalmap below; verified against a 100% pool.
GOAL_LOCATIONS = {
    "spyro1": None,  # built from the engine: eventIdBase + levelId
    "spyro2": {207000: "Spyro 2: Crush Defeated",
               218000: "Spyro 2: Gulp Defeated",
               226000: "Spyro 2: Ripto Defeated"},
    "spyro3": {307000: "Spyro 3: Buzz Defeated",
               316000: "Spyro 3: Spike Defeated",
               325000: "Spyro 3: Scorch Defeated",
               334000: "Spyro 3: Sorceress Defeated"},
}
PIN_START = 50
PIN_STEP = 50
PIN_COLS = 8
HUBLESS = "Bonus"  # sidebar header for lockable levels with no hub (S1 loot)
KEY_ITEM_SIZE = "24,24"      # compact key tiles (fits half-width sidebars)
KEY_ITEM_MARGIN = "1,1"
KEY_COLS = 5                 # cap hub tile rows so the sidebar stays narrow
# Derived per-level gem thresholds get no level-map pin (see is_gem_section);
# they live on a dedicated per-game Gems board so PopTracker can color them by
# access (red inaccessible / green accessible / grey collected).
GEM_SECTIONS = {"25% Gems", "50% Gems", "75% Gems", "All Gems"}
GEM_BOARD_START = 30
GEM_BOARD_STEP = 34
GEM_BOARD_COLS = 12
BG_COLOR_RGB = (0x1c, 0x24, 0x31)  # matches placeholder flat background
ITEM_IMG = "images/items.png"      # single stub sprite for all tracker items
IMG_MARGIN = 60
IMG_DIR = os.path.join(HERE, "images", "maps")
# Map backgrounds resolve through PopTracker's user-override: a player can drop
# `user-override/<package_uid>/images/maps/<map>.png` (see README) and it wins
# over the generated flat PNG. The generator still writes the fallback.
MAP_IMG_DIR = "images/maps"
PACKAGE_UID = "spyro_reignited_ap"
# Optional hand-placed pin coordinates (see place_pins.py), local-only and
# gitignored: {game: {map_name: {section: {"x":int,"y":int}}}}. When a pin is
# present it replaces the generated grid position; unplaced pins keep the grid.
PIN_COORDS = os.path.join(HERE, "pin_coords.json")
# Hard totals guard: the documented per-game location counts must hold
# (spyro1 includes its level-completion events).
EXPECTED_TOTALS = {"spyro1": 237, "spyro2": 184, "spyro3": 289}

# Item pool sizes (guards): how many copies of each stackable item exist.
POOL = {
    "spyro1": {"dragons": 80, "spyro1_eggs": 12},
    "spyro2": {"orbs": 64, "talismans": 14},
    "spyro3": {"eggs": 146},
}


def load_items():
    """The world's per-game item tables (id -> name), loaded standalone with a
    stubbed BaseClasses (only ItemClassification enums are touched)."""
    import types
    fake = types.ModuleType("BaseClasses")

    class FakeIC:
        def __getattr__(self, _):
            return "progression"
    fake.ItemClassification = FakeIC()
    sys.modules["BaseClasses"] = fake
    world_stub = types.ModuleType("srt_world")
    world_stub.__path__ = [os.path.join(REPO, "world")]
    sys.modules["srt_world"] = world_stub
    data_stub = types.ModuleType("srt_world.data")
    data_stub.__path__ = [DATA]
    sys.modules["srt_world.data"] = data_stub
    spec = importlib.util.spec_from_file_location(
        "srt_world.data", os.path.join(DATA, "__init__.py"))
    data_mod = importlib.util.module_from_spec(spec)
    sys.modules["srt_world.data"] = data_mod
    spec.loader.exec_module(data_mod)

    out = {}
    for game in GAMES:
        pkg = f"srt_world.{game}"
        stub = types.ModuleType(pkg)
        stub.__path__ = [os.path.join(REPO, "world", game)]
        sys.modules[pkg] = stub
        for mod in ("Names", "Items"):
            spec = importlib.util.spec_from_file_location(
                f"{pkg}.{mod}", os.path.join(REPO, "world", game, f"{mod}.py"))
            m = importlib.util.module_from_spec(spec)
            sys.modules[f"{pkg}.{mod}"] = m
            spec.loader.exec_module(m)
        out[game] = {code: name
                     for name, code in sys.modules[f"{pkg}.Items"]
                     .item_name_to_id.items()}
    return out


def load_engine():
    """world/data/__init__.py from the sibling checkout, loaded standalone (the
    world package's __init__ needs Archipelago)."""
    spec = importlib.util.spec_from_file_location(
        "srt_pack_data", os.path.join(REPO, "world", "data", "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = load_engine()


def map_name(game: str, region: str) -> str:
    slug = "".join(c for c in region if c.isalnum())
    return f"{game}_{slug}"


def key_code(game: str, level: str) -> str:
    return f"{game}_key_" + "".join(c for c in level if c.isalnum()).lower()


def hub_of(game: str, data, region: str):
    """The hub a level belongs to. Spyro 1 reads the level's own `hub` field;
    the tabular games take the latest homeworld at or before the region in
    play order (the rule world/gates.py homeworld_of uses). Hubs and hubless
    bonus regions return None."""
    if game == "spyro1":
        for level in data.raw["levels"]:
            if level["name"] == region:
                return level.get("hub")
        return None
    order = list(data.raw["regions"])
    homes = data.raw["homeworlds"]
    prior = [h for h in order[:order.index(region) + 1] if h in homes]
    return prior[-1] if prior else None


def hub_groups(game: str, data, groups: list) -> list:
    """[(hub, [region, ...]), ...] in play order: the game's lockable levels
    grouped under their hub. Hubs themselves drop out; a lockable level with
    no hub (e.g. Spyro 1's bonus Gnasty's Loot) lands in a trailing group so
    its key tile is never lost."""
    order: list = []
    by_hub: dict = {}
    for region, _rows in groups:
        if region not in LOCKABLE[game]:
            continue
        hub = hub_of(game, data, region) or HUBLESS
        if hub not in by_hub:
            by_hub[hub] = []
            order.append(hub)
        by_hub[hub].append(region)
    return [(hub, by_hub[hub]) for hub in order]


def counter_grid(game: str) -> dict:
    """The Overview tab's counter row(s)."""
    return {"type": "itemgrid", "h_alignment": "left",
            "rows": OVERVIEW_ROWS[game]}


def key_rows(game: str, regions: list) -> list:
    """A hub's key tiles as up to KEY_COLS columns per row, so the sidebar's
    width is bounded no matter how many levels the hub holds."""
    codes = [key_code(game, region) for region in regions]
    return [codes[i:i + KEY_COLS] for i in range(0, len(codes), KEY_COLS)]


def key_sidebar(game: str, data, groups: list) -> dict:
    """The persistent key column: each hub's per-level unlock toggles under a
    slim hub label, capped to KEY_COLS columns. Compact tiles keep it narrow
    so it does not starve the level tabs at half width."""
    widgets = []
    for hub, regions in hub_groups(game, data, groups):
        widgets.append({"type": "text", "text": hub})
        widgets.append({
            "type": "itemgrid", "h_alignment": "left",
            "item_size": KEY_ITEM_SIZE, "item_margin": KEY_ITEM_MARGIN,
            "rows": key_rows(game, regions)})
    return {"type": "array", "orientation": "vertical",
            "content": widgets}


def is_gem_section(section: str) -> bool:
    """Whether a section is a derived per-level gem threshold. Those are
    percentages, not physical map spots, so they live on a dedicated per-game
    Gems board (gem_board) with coarse access rules, giving PopTracker's
    red/accessible/collected pin colors; they stay out of the level maps."""
    return section in GEM_SECTIONS


def gem_levels(groups: list) -> list:
    """[(level, [gem section, ...]), ...] in play order, only levels that have
    gem thresholds, in the engine's tier order (25/50/75/All)."""
    out = []
    for region, rows in groups:
        secs = [sec for _name, sec, _id in rows if is_gem_section(sec)]
        if secs:
            out.append((region, secs))
    return out


def gem_board(game: str, levels: list) -> tuple:
    """The Gems board map and its pins. Returns (map_name, fields, background,
    {full location name: {x, y}}). Pins are a grid (GEM_BOARD_COLS wide) in
    level order so each level's 25/50/75/All sit together. Bounded size keeps
    the tab from ballooning (Tabs sizes the tracker to its tallest tab)."""
    total = sum(len(secs) for _lvl, secs in levels)
    start, step = GEM_BOARD_START, GEM_BOARD_STEP
    cols = min(GEM_BOARD_COLS, max(total, 1))
    n_rows = (total + GEM_BOARD_COLS - 1) // GEM_BOARD_COLS if total else 1
    pins = {}
    cell = 0
    for level, secs in levels:
        for sec in secs:
            full = PREFIX[game] + f"{level}: {sec}"
            pins[full] = {"x": start + (cell % GEM_BOARD_COLS) * step,
                          "y": start + (cell // GEM_BOARD_COLS) * step}
            cell += 1
    name = f"{game}_Gems"
    fields = {"location_size": 24, "location_border_thickness": 2,
              "location_shape": "rect", "img": f"{MAP_IMG_DIR}/{name}.png"}
    size = (start * 2 + (cols - 1) * step,
            start * 2 + (n_rows - 1) * step)
    return name, fields, size, pins


def gem_access_rules(game: str, level: str, section: str):
    """Coarse access rule for a gem threshold: it is accessible unless the
    level is locked this seed and its key has not arrived. Emitted only for
    lockable levels (hubs/bonus are always open -> no rule -> green). The rule
    calls srt_gem_gate in autotracking.lua, which reads slot_data.level_keys."""
    if level not in LOCKABLE[game]:
        return None
    return [f"$srt_gem_gate|{game}|{level}|{key_code(game, level)}"]


def pin(i: int, count: int) -> dict:
    """Grid pin for check i of count in a region. The grid is centered
    horizontally so fewer-check regions look deliberate."""
    cols = min(PIN_COLS, max(count, 1))
    rows = (count + cols - 1) // cols if count else 1
    x = PIN_START + (i % cols) * PIN_STEP
    y = PIN_START + (i // cols) * PIN_STEP
    return {"x": x, "y": y}


def load_pin_coords() -> dict:
    """Hand-placed pin coordinates from PIN_COORDS, or {} when absent. The file
    is local-only (gitignored); a missing or malformed file just means the
    generated grid is used everywhere."""
    if not os.path.isfile(PIN_COORDS):
        return {}
    try:
        with open(PIN_COORDS, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as err:
        print(f"WARN: ignoring {PIN_COORDS}: {err}")
        return {}
    return data if isinstance(data, dict) else {}


def placed_pin(coords: dict, game: str, mname: str, rows: list, i: int):
    """The hand-placed coordinate for check i of a region, or None. Matches by
    section label (unique within a level)."""
    table = coords.get(game, {}).get(mname)
    if not isinstance(table, dict):
        return None
    entry = table.get(rows[i][1])
    if isinstance(entry, dict) and "x" in entry and "y" in entry:
        return {"x": int(entry["x"]), "y": int(entry["y"])}
    return None


def png_canvas(width: int, height: int, rgb) -> bytes:
    """A minimal flat-color RGB PNG (stdlib only). Each row is a filter byte
    plus `width` pixels."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(ctype: bytes, data: bytes) -> bytes:
        block = struct.pack(">I", len(data)) + ctype + data
        return block + struct.pack(">I", zlib.crc32(ctype + data) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def write_map_backgrounds(map_files: dict) -> None:
    """Flat-color background per map, sized to the pin grid + margin."""
    os.makedirs(IMG_DIR, exist_ok=True)
    for path, (width, height) in map_files.items():
        with open(path, "wb") as f:
            f.write(png_canvas(width, height, BG_COLOR_RGB))


def checks_spyro1(data) -> list:
    """(region, [(full location name, section, id), ...]) per Spyro 1 level,
    in level order. Dragons/eggs/skill points come from the JSON; gem checks
    and level-completion events from the data engine's derivation (the same
    the apworld uses)."""
    prefix = PREFIX["spyro1"]
    levels = []
    for level in data.raw["levels"]:
        rows = []
        for check in level["checks"]:
            plain = check["name"].split(": ", 1)[1]
            rows.append((prefix + check["name"], plain, check["id"]))
        for loc_id, name, _pct in data.gem_threshold_checks(level):
            rows.append((prefix + name, short_section(name), loc_id))
        event = data.event_check(level)
        if event:
            rows.append((prefix + event[1], short_section(event[1]), event[0]))
        if rows:
            levels.append((level["name"], rows))
    return levels


def checks_tabular(game: str, data) -> list:
    """spyro2/spyro3: straight from the engine's per-region rows (id =
    baseId + tableOffset * regionIndex + row)."""
    regions = []
    for region, rows in data.regions.items():
        entries = []
        for row in rows:
            plain = row["plain"]
            section = plain.split(": ", 1)[1] if ": " in plain else plain
            entries.append((row["name"], section, row["id"]))
        if entries:
            regions.append((region, entries))
    return regions


def short_section(name: str) -> str:
    """Section label from a full S1 location name (drop the level prefix);
    events carry no prefix and pass through."""
    return name.split(": ", 1)[1] if ": " in name else name


def build_all() -> dict:
    maps = {}
    backgrounds = {}
    layouts = {"tracker_default": None, "header_items": None,
               "game_tabs": None, "tracker_broadcast": None}
    locations = {}
    idmaps = {}
    seen_ids = set()
    coords = load_pin_coords()
    n_placed = 0

    for game in GAMES:
        data = ENGINE.load(game)
        groups = (checks_spyro1(data) if game == "spyro1"
                  else checks_tabular(game, data))
        levels = gem_levels(groups)
        board = board_pins = None
        if levels:
            board, fields, size, board_pins = gem_board(game, levels)
            maps[board] = fields
            backgrounds[os.path.join(IMG_DIR, f"{board}.png")] = size
        doc = []
        idmap = {}
        for region, rows in groups:
            children = []
            for i, (name, section, loc_id) in enumerate(rows):
                if loc_id in seen_ids:
                    sys.exit(f"ERROR: duplicate location id {loc_id} "
                             f"({name!r})")
                seen_ids.add(loc_id)
                idmap[loc_id] = {"loc": name, "sec": section}
                child = {
                    "name": name,
                    "sections": [{"name": section, "item_count": 1}],
                }
                if is_gem_section(section):
                    # On the Gems board, colored by the coarse level gate.
                    child["map_locations"] = [
                        dict(map=board, **board_pins[name])]
                    child["access_rules"] = gem_access_rules(game, region,
                                                             section)
                else:
                    coord = placed_pin(coords, game, map_name(game, region),
                                       rows, i)
                    if coord is None:
                        coord = pin(i, len(rows))
                    else:
                        n_placed += 1
                    child["map_locations"] = [dict(map=map_name(game, region),
                                                   **coord)]
                children.append(child)
            doc.append({"name": region, "short_name": region,
                        "children": children})
            img = f"{MAP_IMG_DIR}/{map_name(game, region)}.png"
            # Size the placeholder to the pinned checks only (gems have none).
            pinned = sum(1 for c in children if "map_locations" in c)
            grid_cols = min(PIN_COLS, pinned) if pinned < PIN_COLS else PIN_COLS
            n_rows = (pinned + grid_cols - 1) // grid_cols if pinned else 1
            width = PIN_START * 2 + (min(PIN_COLS, pinned) - 1) * PIN_STEP \
                if pinned else PIN_START * 2
            height = PIN_START * 2 + (n_rows - 1) * PIN_STEP
            maps[map_name(game, region)] = {
                "location_size": 24,
                "location_border_thickness": 2,
                "location_shape": "rect",
                "img": img,
            }
            backgrounds[os.path.join(IMG_DIR,
                                     f"{map_name(game, region)}.png")] = \
                (width, height)
        locations[game] = doc
        idmaps[game] = idmap

        tabs = [{"title": "Overview", "content": counter_grid(game)}]
        if levels:
            tabs.append({"title": "Gems",
                         "content": {"type": "map", "maps": [board]}})
        for region, _rows in groups:
            tabs.append({"title": region,
                         "content": {"type": "map",
                                     "maps": [map_name(game, region)]}})
        # The key column is docked left of the tabbed view so it stays on
        # screen while the player clicks through the level tabs.
        layouts[f"{game}_tabs"] = {
            "type": "dock",
            "content": [
                {"type": "layout", "key": f"{game}_sidebar", "dock": "left"},
                {"type": "tabbed", "tabs": tabs},
            ]}
        layouts[f"{game}_sidebar"] = key_sidebar(game, data, groups)

    ordered_maps = [{"name": name, **fields} for name, fields in maps.items()]

    layouts["header_items"] = {"type": "itemgrid",
                               "h_alignment": "left",
                               "rows": HEADER_ROWS}
    layouts["game_tabs"] = {
        "type": "tabbed",
        "tabs": [{"title": TITLES[game],
                  "content": {"type": "layout",
                              "key": f"{game}_tabs"}} for game in GAMES]}
    # Root = dock (single child of the TrackerView, which only sizes its
    # first child): header docked top, tabbed view as the floater filling
    # the remaining window. A "container" root would leave the tabs sized
    # to the transient boot size (~300px wide) — trap content on the left.
    for name in ("tracker_default", "tracker_broadcast"):
        layouts[name] = {
            "type": "dock",
            "content": [
                {"type": "layout", "key": "header_items", "dock": "top"},
                {"type": "layout", "key": "game_tabs"},
            ]}

    return {"maps": ordered_maps, "layouts": layouts,
            "locations": locations, "idmaps": idmaps,
            "backgrounds": backgrounds,
            "items": build_items(ITEM_MAPS),
            "itemmaps": ITEM_MAPS,
            "goalmaps": build_goalmap(ITEM_MAPS),
            "n_placed": n_placed}


def lua_idmap(idmaps: list) -> str:
    """One merged lookup table over all three games' id maps (a Lua chunk can
    hold a single `return`)."""
    lines = [
        "-- AUTO-GENERATED by poptracker-pack/gen_pack.py from world/data.",
        "-- Do not edit by hand.",
        "-- Regenerate: python3 <repo>/poptracker-pack/gen_pack.py",
        "-- AP location id -> [\"@<Location>\", \"<Section>\"] for the",
        "-- autotracking handlers.",
        "return {",
    ]

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    ids = sorted(set().union(*[set(m) for m in idmaps]))
    for loc_id in ids:
        for idmap in idmaps:
            if loc_id not in idmap:
                continue
            entry = idmap[loc_id]
            lines.append(f'    [{loc_id}] = {{"{esc(entry["loc"])}", '
                         f'"{esc(entry["sec"])}"}},')
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Items: tracker items + the AP id -> action map
# ---------------------------------------------------------------------------

COUNTER_BY_NAME = {
    "Spyro 1: Dragon": "dragons",
    "Spyro 1: Dragon Egg": "spyro1_eggs",
    "Spyro 2: Orb": "orbs",
    "Spyro 3: Dragon Egg": "eggs",
}


def classify_item(game: str, name: str):
    """An AP item name -> list of (kind, code, level) tracker actions for
    spyro_itemmap.lua: kind "count" = +1 per copy (consumable), "toggle" =
    activate. Level (third value) = tab title to ActivateTab on receive.
    Events, bosses, fillers and traps are deliberately ignored (no
    meaningful tracker display)."""
    if name in COUNTER_BY_NAME:
        return [("count", COUNTER_BY_NAME[name], None)]
    if name.endswith(" Key"):
        plain = name.split(": ", 1)[1]
        level = plain[:-len(" Key")]
        return [("count", f"s{game[-1]}_keys", level),
                ("toggle", key_code(game, level), None)]
    if game == "spyro2" and name.endswith(" Ability"):
        ab = name.split(": ")[1].removesuffix(" Ability").lower()
        return [("toggle", f"s2_{ab}", None)]
    if name.startswith("Spyro 3: Sparx "):
        pw = name.removeprefix("Spyro 3: Sparx ").lower().replace(" ", "")
        return [("toggle", f"sparx_{pw}", None)]
    return None


def key_counts(itemmaps: dict) -> dict:
    return {game: sum(1 for name in idmap.values() if name.endswith(" Key"))
            for game, idmap in itemmaps.items()}


def build_items(itemmaps: dict) -> list:
    """items.json: the display items — three per-game toggles (visibility /
    counters in the Overview), stackable counters, ability + Sparx toggles."""
    keys = key_counts(itemmaps)
    items = [
        {"name": "Spyro 1 played", "type": "toggle", "img": ITEM_IMG,
         "codes": "spyro1_played"},
        {"name": "Spyro 2 played", "type": "toggle", "img": ITEM_IMG,
         "codes": "spyro2_played"},
        {"name": "Spyro 3 played", "type": "toggle", "img": ITEM_IMG,
         "codes": "spyro3_played"},
    ]
    counters = [("dragons", "Dragons", 80),
                ("spyro1_eggs", "Spyro 1 Eggs", 12),
                ("orbs", "Orbs", 64),
                ("talismans", "Talismans", 14),
                ("eggs", "Spyro 3 Eggs", 146)]
    # Talismans come from the S2 item table's band, not a pool name; the count
    # must still advance. We derive it from talisman checks instead: there is
    # no "Spyro 2: Talisman" item — talismans release from talisman locations,
    # arriving as whatever is shuffled there.
    for code, label, max_q in counters:
        items.append({"name": label, "type": "consumable",
                      "img": ITEM_IMG, "codes": code,
                      "max_quantity": max_q})
    for game in GAMES:
        items.append({"name": f"{TITLES[game]} Keys", "type": "consumable",
                      "img": ITEM_IMG, "codes": f"s{game[-1]}_keys",
                      "max_quantity": keys[game]})
    # Per-level key toggles: lit = level unlocked (Overview grid row), so the
    # player sees WHICH levels are unlocked, not just how many.
    for game in GAMES:
        for _item_id, name in sorted(itemmaps[game].items(),
                                     key=lambda kv: int(kv[0])):
            actions = classify_item(game, name)
            for kind, _code, level in actions or []:
                if level and kind == "count":
                    items.append({
                        "name": level, "type": "toggle", "img": ITEM_IMG,
                        "codes": key_code(game, level),
                        "ignore_user_input": True})
    toggles = [("s2_swim", "S2 Swim"), ("s2_climb", "S2 Climb"),
               ("s2_headbash", "S2 Headbash"),
               ("sparx_gemcollectrange", "Sparx Gem Collect Range"),
               ("sparx_extrahitpoint", "Sparx Extra Hit Point"),
               ("sparx_chestbreaking", "Sparx Chest Breaking")]
    for code, name in toggles:
        items.append({"name": name, "type": "toggle", "img": ITEM_IMG,
                      "codes": code})
    return items


def lua_itemmap(itemmaps: dict) -> str:
    lines = [
        "-- AUTO-GENERATED by poptracker-pack/gen_pack.py from world data.",
        "-- Do not edit by hand.",
        "-- Regenerate: python3 <repo>/poptracker-pack/gen_pack.py",
        "-- AP item id -> {code, kind, level}: kind=count (+1 per copy) or",
        '-- kind=toggle; level = tab title to ActivateTab on key receive',
        "-- (nil for everything else). Unlisted ids are ignored.",
        "return {",
    ]

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    entries = []
    for game, idmap in itemmaps.items():
        for item_id, name in sorted(idmap.items(), key=lambda kv: int(kv[0])):
            actions = classify_item(game, name)
            for k, (kind, code, level) in enumerate(actions or []):
                # first action of a key entry carries the ActivateTab level
                level_part = f', "{esc(level)}"' if (level and k == 0) \
                    else ", nil"
                entries.append((item_id, kind, code, level_part))
    for item_id, kind, code, level_part in entries:
        lines.append(f'    [{item_id}] = {{"{esc(code)}","{kind}"'
                     f'{level_part}}},')
    lines.append("}")
    return "\n".join(lines) + "\n"


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def lua_levels(locations: dict, lockable: dict) -> str:
    """Per game: tab title -> {"@Loc/Sec" refs, tile_code} for levels that
    have an unlock tile (key items exist only for lockable levels; hubs are
    always open and carry no tile). The autotracker aggregates refs to
    compute each tile's check overlay."""
    lines = [
        "-- AUTO-GENERATED by poptracker-pack/gen_pack.py from world/data.",
        "-- Do not edit by hand.",
        "-- Regenerate: python3 <repo>/poptracker-pack/gen_pack.py",
        "-- game -> level -> {refs, tile}: refs are '@Location/Section' codes",
        "-- (aggregated for the tile's remaining-count overlay), tile the",
        '-- per-level unlock item\'s code. Lockable levels only (key items',
        "-- exist only for them; hubs are always open, no tile).",
        "return {",
    ]
    for game in GAMES:
        lines.append("    " + game + " = {")
        for group in locations[game]:
            level = group["name"]
            if level not in lockable[game]:
                continue
            refs = [f'"@{child["name"]}/{child["sections"][0]["name"]}"'
                    for child in group["children"]]
            lines.append(f'        ["{esc(level)}"] = '
                         f'{{refs={{{", ".join(refs)}}}, '
                         f'tile="{key_code(game, level)}"}},')
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def lockable_levels(itemmaps: dict) -> dict:
    """game -> set of lockable level (tab) titles: levels whose key item
    exists ("<X> Key" in the item table)."""
    out = {}
    for game, idmap in itemmaps.items():
        levels = set()
        for name in idmap.values():
            if name.endswith(" Key"):
                levels.add(name.split(": ", 1)[1][:-len(" Key")])
        out[game] = levels
    return out


def build_goalmap(itemmaps: dict) -> dict:
    """game key -> {goal event ITEM id: {loc, name}}. The slot's goal_location
    is a location id; autotracking resolves it to its event item id through
    loc (S1 via the data engine's event derivation, S2/S3 via the verified
    GOAL_LOCATIONS table)."""
    inv = {game: {name: int(item_id)
                  for item_id, name in itemmaps[game].items()}
           for game in GAMES}
    out = {}
    for game in GAMES:
        rows = {}
        if game == "spyro1":
            data = ENGINE.load("spyro1")
            for level in data.raw["levels"]:
                event = data.event_check(level)
                if not event:
                    continue
                loc_id, name = event
                full = "Spyro 1: " + name
                item_id = inv["spyro1"].get(full)
                if item_id is None:
                    sys.exit(f"ERROR: spyro1 event {full!r} has no item")
                rows[item_id] = {"loc": loc_id, "name": full}
        else:
            for loc_id, name in GOAL_LOCATIONS[game].items():
                item_id = inv[game].get(name)
                if item_id is None:
                    sys.exit(f"ERROR: {game} goal item {name!r} is not in "
                             f"the item table")
                rows[item_id] = {"loc": loc_id, "name": name}
        out[game] = rows
    return out


def lua_goalmap(goalmap: dict) -> str:
    lines = [
        "-- AUTO-GENERATED by poptracker-pack/gen_pack.py from world data.",
        "-- Do not edit by hand.",
        "-- Regenerate: python3 <repo>/poptracker-pack/gen_pack.py",
        "-- game key -> {completion-event ITEM id: {loc, name}}: slot_data",
        "-- goal_location (a location id) resolves to its event item through",
        "-- loc; ALL_DRAGONS-style goals emit goal_location = 0 (unverifiable",
        "-- counter goals — reporting stays off, the server side is still",
        "-- correct).",
        "return {",
    ]
    for game in GAMES:
        lines.append(f"    {game} = {{")
        for item_id in sorted(goalmap[game]):
            row = goalmap[game][item_id]
            lines.append(f'        [{item_id}] = {{loc={row["loc"]}, '
                         f'name="{esc(row["name"])}"}},')
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def dump_json(doc) -> str:
    return json.dumps(doc, indent=2) + "\n"


ENGINE = load_engine()
ITEM_MAPS = None  # set by main(); build_all is called after
LOCKABLE = {}  # game -> set of lockable level titles (set by main())


def key_of_level(level: str) -> bool:
    return True


def output_files(built: dict) -> dict:
    out = {
        os.path.join(HERE, "maps", "maps.json"):
            dump_json(built["maps"]),
        os.path.join(HERE, "scripts", "spyro_locmap.lua"):
            lua_idmap([built["idmaps"][game] for game in GAMES]),
        os.path.join(HERE, "scripts", "spyro_itemmap.lua"):
            lua_itemmap(ITEM_MAPS),
        os.path.join(HERE, "scripts", "spyro_goalmap.lua"):
            lua_goalmap(built["goalmaps"]),
        os.path.join(HERE, "scripts", "spyro_levels.lua"):
            lua_levels(built["locations"], LOCKABLE),
        os.path.join(HERE, "items", "items.json"):
            dump_json(built["items"]),
    }
    for game in GAMES:
        out[os.path.join(HERE, "locations", f"{game}.json")] = \
            dump_json(built["locations"][game])
    out[os.path.join(HERE, "layouts", "layouts.json")] = \
        dump_json(built["layouts"])
    return out


# backwards-compat alias used by main()
outputs = output_files


def main() -> None:
    global ITEM_MAPS
    check = "--check" in sys.argv[1:]
    ITEM_MAPS = load_items()
    for game, levels in lockable_levels(ITEM_MAPS).items():
        LOCKABLE[game] = levels
    built = build_all()
    files = outputs(built)
    changed = []
    if check:
        for path, text in files.items():
            with open(path) as f:
                if f.read() != text:
                    changed.append(path)
        for path, (width, height) in built["backgrounds"].items():
            if not os.path.isfile(path):
                changed.append(path)
                continue
            import struct
            with open(path, "rb") as f:
                header = f.read(33)
            if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
                changed.append(path)
            else:
                w, h = struct.unpack(">II", header[16:24])
                if (w, h) != (width, height):
                    changed.append(path)
    else:
        for path, text in files.items():
            with open(path, "w") as f:
                f.write(text)
        write_map_backgrounds(built["backgrounds"])
        # Drop stale backgrounds for maps that no longer exist.
        keep = set(built["backgrounds"])
        if os.path.isdir(IMG_DIR):
            for name in os.listdir(IMG_DIR):
                path = os.path.join(IMG_DIR, name)
                if name.endswith(".png") and path not in keep:
                    os.remove(path)

    counts = {game: sum(len(idmap) for idmap in [built["idmaps"][game]])
              for game in GAMES}
    for game, want in EXPECTED_TOTALS.items():
        if counts[game] != want:
            sys.exit(f"ERROR: {game} generated {counts[game]} locations, "
                     f"expected {want}")
    n_maps = len(built["maps"])
    n_tabs = sum(len(built["layouts"][f"{g}_tabs"]["content"][1]["tabs"])
                 for g in GAMES)
    summary = (f"{n_maps} maps (one per level/region), "
               + ", ".join(f"{g} {counts[g]}" for g in GAMES)
               + f" locations, {n_tabs} tabs, {built['n_placed']} placed pins")
    if check:
        if changed:
            sys.exit("ERROR: generated files out of date (add the pack to "
                     "the build or run gen_pack.py): "
                     + ", ".join(changed))
        print(f"gen_pack.py --check ok: {summary}")
    else:
        print(f"wrote {len(files)} files: {summary}")


if __name__ == "__main__":
    main()