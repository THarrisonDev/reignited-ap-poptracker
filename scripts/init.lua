-- Author: Tim Harrison
-- Created: 2026-10-09
-- Updated: 2026-10-31

-- Spyro Reignited Trilogy AP pack entry point: load the generated data
-- (gen_pack.py) and the layout, then start Archipelago autotracking.

-- View shape: no map art. Root tabbed layout -> one tab per game ->
-- "Overview" tab (counters) + one tab per level/region. Each level tab is a
-- trivial map (generated flat-color background, computed grid pins), so real
-- AP locations/sections/access rules survive without art.
-- See layouts/layouts.json.

-- Coarse access-rule hook for the Gems board (gen_pack's gem_access_rules
-- emits "$srt_gem_gate|<game>|<level>|<key code>"). PopTracker calls this with
-- no arguments and parses the rule's trailing args itself. It returns true
-- (accessible/green) unless the connected seed locks the level and the key has
-- not been received. SRT_LOCKED is filled by autotracking.lua on connect
-- (nil before then, and in non-AP mode, meaning "no locks known").
SRT_LOCKED = nil
function srt_gem_gate(game, level, key)
    local locked = SRT_LOCKED
    if type(locked) ~= "table" or type(locked[game]) ~= "table"
            or not locked[game][level] then
        return true
    end
    local obj = Tracker:FindObjectForCode(key)
    return obj ~= nil and obj.Active
end

Tracker:AddItems("items/items.json")

-- Generated from world/data/*.json by gen_pack.py (single source) — do not
-- hand-edit. Rerun `python3 poptracker-pack/gen_pack.py` after data changes.
Tracker:AddMaps("maps/maps.json")
Tracker:AddLocations("locations/spyro1.json")
Tracker:AddLocations("locations/spyro2.json")
Tracker:AddLocations("locations/spyro3.json")

Tracker:AddLayouts("layouts/layouts.json")
Tracker:AddLayouts("layouts/broadcast.json")

if Archipelago.AddClearHandler then
    ScriptHost:LoadScript("scripts/autotracking.lua")
end