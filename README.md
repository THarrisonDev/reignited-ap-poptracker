# PopTracker pack — Spyro Reignited Trilogy

Archipelago-aware PopTracker pack scaffold. PACKS.md (from PopTracker's docs)
is the interface reference.

## Responsible AI Usage Disclosure

This project was written while leveraging open-weight large
language models, primarily self-hosted with open source tools.
All usage happened within a controlled development workflow and
was narrowly spec'd by the developer. This workflow has been
provided including all tools and processes. It can be found in each
project in the [PROCESS.md](https://github.com/THarrisonDev/reignited-ap/blob/main/PROCESS.md) on root.

Remember, these things are tools meant to EMPOWER you never stop thinking.

 **Brains > Bots <3**
 -Tim

Contributors are held to the same expectation. AI-assisted contributions are
welcome, but the human author owns the result: correctness, legibility,
tests, and the decision to merge. Say so in your pull request — disclosure is
there to keep review honest, not to reject a change. We will not be accepting
any code generated in a blind agentic manner and will automatically reject any
PRs directly attributed to AI tools.

## View shape (decided)

No map art. A persistent per-game key sidebar next to nested tabs:

```
tracker_default (container)
├─ dock top: header itemgrid (per-game toggles + counters)
└─ game_tabs (tabbed)            — "Spyro 1" | "Spyro 2" | "Spyro 3"
   └─ spyroN_tabs (dock)
      ├─ dock left: spyroN_sidebar — hub-grouped per-level key toggles,
      │  stays on screen while the level tabs switch
      └─ tabbed                  — "Overview" | "Gems" | one tab per level
         ├─ Overview tab: itemgrid of counters
         ├─ Gems tab: every level's 25/50/75/All gem thresholds as pins on a
         │  bounded per-game "Gems board" map, in level order. Gem thresholds
         │  have no physical spot, so they live here; being map pins, they get
         │  PopTracker's accessibility colors — red inaccessible / green
         │  accessible / grey collected — from a coarse access rule
         │  (lockable level needs its key; see srt_gem_gate).
         └─ level tab: type "map" backed by a TRIVIAL map (plain background
            image; pins in a computed grid). Keeps real AP locations, sections,
            access rules and tooltips without any art.
```

The sidebar groups each game's lockable levels under their hub (S1 from the
level's `hub` field; S2/S3 by homeworld play order — the same rule
`world/gates.py` uses), so the key column reads per-hub and never scrolls away.
Tiles are compact (24px) and each hub caps at `KEY_COLS` (5) columns, keeping
the sidebar narrow enough to leave the level tabs usable at half width.

Tab strips are static (Lua cannot hide tabs at runtime); the generator emits
one tab per level/region from `world/data/*.json`. Level keys arriving via AP
can `Tracker:UiHint("ActivateTab", ...)` to jump to the unlocked level's tab.

## Scaffold layout

| Path                        | Role                                                      |
| --------------------------- | --------------------------------------------------------- |
| `manifest.json`             | Pack manifest; `ap`/`apmanual`/`aphintgame` variant flags |
| `settings.json`             | Crisp scaling, deferred logic updates                      |
| `gen_pack.py`               | Generator: world/data -> maps, locations, layouts, locmap  |
| `scripts/init.lua`          | Entry point — loads items/maps/locations/layouts          |
| `scripts/autotracking.lua`  | AP handlers (clear/item/location/scout)                   |
| `scripts/spyro_locmap.lua`  | GENERATED: AP id -> `@Location/Section` for autotracking   |
| `items/items.json`          | GENERATED tracker items (counters, keys, toggles)         |
| `maps/maps.json`            | Trivial per-level maps + generated `images/maps/*.png`     |
| `locations/spyro{1,2,3}.json` | GENERATED: one group per level, one child per check      |
| `layouts/*.json`            | GENERATED nested-tab layouts (game tabs, overview/level)   |
| `scripts/spyro_itemmap.lua` | GENERATED: AP item id -> counter/toggle action             |
| `images/placeholder.png`    | Placeholder item sprite                                    |
| `import_maps.py`            | Optional: pull the game's minimaps into user-override      |
| `place_pins.py`             | Optional: local web tool to place map pins (-> pin_coords) |

## Real map images (bring your own)

The repo ships flat placeholder backgrounds. The game stores a real minimap per
level (`UI_MiniMap_<n>` in `Falcon/Content/Paks`, `<n>` = the level's `LS<n>`
number), which PopTracker can show via its **user-override** mechanism: files
under `user-override/<package_uid>/` are read before the pack's own, so a
player can drop in art without the repo distributing any (it is (c) Activision).

Personal use only — extracted for the player's own copy, never committed:

```
python3 poptracker-pack/import_maps.py            # all games -> ~/PopTracker/user-override/spyro_reignited_ap/images/maps/
python3 poptracker-pack/import_maps.py --game 1 --keep-alpha
python3 poptracker-pack/import_maps.py --dry-run  # list, extract nothing
```

It needs `repak` and Pillow, reads the player's installed paks, decodes the
uncompressed BGRA textures to `<game>_<Level>.png` (the generated map names),
and composites them over the pack background. Boss arenas and sub-levels have
no minimap in the game (11 of 101); those are warned about and fall back to the
placeholder. Restart PopTracker to pick the images up.

## Placing pins (bring your own effort)

`gen_pack.py` drops pins on a synthetic grid because nothing knows where a
check actually is. To place them for real, run the local placement tool:

```
python3 poptracker-pack/place_pins.py            # http://127.0.0.1:8765/
python3 poptracker-pack/place_pins.py --game 1 --port 9000 --no-browser
```

It serves each level map with the current pins overlaid, so you click/drag
each check onto its spot. Left-click empty space places the selected check;
drag a pin to move it; right-click clears it back to the grid. Progress is
shown per level; every change saves automatically to `pin_coords.json`
(local-only, gitignored). Run `import_maps.py` first to place onto the real
minimaps instead of the placeholder.

Then regenerate — placed pins replace the grid, unplaced ones keep it:

```
python3 poptracker-pack/gen_pack.py     # "... N placed pins"
```

`pin_coords.json` is `{game: {map_name: {section: {x, y}}}}`, keyed by the
level's on-map section label. It is treated like the map art: derived from the
game, personal use, never committed.

## TODOs (work one at a time)

1. ~~items.json~~ DONE (stub visuals): counter consumables (dragons 80,
   S1 eggs 12, orbs 64, talismans 14, S3 eggs 146), per-game key counters
   (29/25/33), ability + Sparx toggles. `gen_pack.py` builds it from the
   real item tables (stubbed-BaseClasses import of `world/<game>/Items.py`)
   and emits `scripts/spyro_itemmap.lua` (AP id -> counter/toggle action);
   `autotracking.lua` advances/activates on receive. Boss events, fillers,
   traps and gem stacks are deliberately unmapped. Overview grids reference
   the codes via `OVERVIEW_ROWS`/`HEADER_ROWS` in gen_pack.py.
2. ~~maps/locations/layouts generator~~ DONE: `gen_pack.py` generates all of
   it from `world/data/*.json` through the standalone data engine. After
   editing world data: `python3 poptracker-pack/gen_pack.py`; CI-style guard:
   `gen_pack.py --check`.
3. **autotracking.lua** (mostly working): onItem advances counters/toggles
   via the generated itemmap; onLocation clears sections via the locmap.
   Still missing: ClearHandler slot_data parsing + `Archipelago:Get`/
   `SetNotify`, goal wiring (mirror
   `client/ue4ss_mod/srt_bridge/Scripts/goal_watch.lua` — ALL_DRAGONS has no
   single goal location), `ActivateTab` hints on level keys, backfilling
   `Archipelago.CheckedLocations`/received-item backlog on connect.
4. **apmanual**: if we want the tracker to send checks (game_name is
   "Spyro Reignited Trilogy"), wire `Archipelago:LocationChecks` — careful:
   the mod/checkd are the real check senders; decide whether manual sending
   is allowed at all to avoid double-send.
5. **images**: real counters/sprites (still the stub sprite). Map art is
   handled by the optional `import_maps.py` user-override path; the shipped
   backgrounds stay flat placeholders.
6. **Overview tabs**: counters + `recentpins` widget for a "what's left"
   list. Per-level key toggles now live in the persistent hub-grouped sidebar.