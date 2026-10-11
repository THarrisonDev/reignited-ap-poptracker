-- Author: Tim Harrison
-- Created: 2026-10-09
-- Updated: 2026-10-11

-- Archipelago autotracking for Spyro Reignited Trilogy.
--
-- Data flow (mirrors the UE4SS client, see AGENTS.md):
--   - connected slot = one SRT multiworld slot, may include any subset of
--     spyro1/spyro2/spyro3 (slot_data.included_games)
--   - location ids: game x 100000 + offset (S1=100000, S2=200000, S3=300000)
--   - item ids: same block; the generated spyro_itemmap.lua maps the shuffle
--     items (dragons/eggs/orbs, keys, abilities, Sparx powers) to tracker
--     items; events/bosses/fillers are deliberately ignored
--   - slot_data games.<game> carries options, level_keys, gate_requirements
--     (S1 only), goal_location; required_games lists the goal-bearing games
--   - goal: report GOAL when every required game's goal event item has been
--     received (goal_watch.lua semantics); ALL_DRAGONS emits goal_location
--     = 0, which keeps that game's reporting off (server-side win condition
--     is still correct, we just cannot verify it)
--
-- Generated tables (poptracker-pack/gen_pack.py):
--   spyro_locmap.lua   id -> {"@<Location>", "<Section>"}
--   spyro_itemmap.lua  id -> {"<code>", "count"|"toggle", level|nil}

local AP_MAPS = require("scripts.spyro_locmap")
local AP_ITEMS = require("scripts.spyro_itemmap")
local AP_GOALS = require("scripts.spyro_goalmap")

-- Goal reporting off for now: the real client (checkd/game mod) owns GOAL.
-- Flip to true when testing against a throwaway server (TODO 3 isolated
-- server test); goal *tracking* (pings in the console) stays on either way.
local ALLOW_GOAL_REPORT = false

-- Generated table: spyro_levels.lua — game -> level -> {"@Loc/Sec", ...}
local LEVEL_SECTIONS = require("scripts.spyro_levels")

-- connection state ----------------------------------------------------------
local PLAYER_ID = -1
local ITEM_INDEX = -1          -- last index seen (backlog replays are skipped)
local SLOT_DATA = nil
local GOALS_PENDING = {}       -- goal item id -> true (required, not received)
local GOAL_REPORTED = false

local function section(location_id)
    local entry = AP_MAPS[location_id]
    if not entry then
        return nil
    end
    return Tracker:FindObjectForCode("@" .. entry[1] .. "/" .. entry[2])
end

-- Coarse access rule for the Gems board (gen_pack's gem_access_rules emits
-- "$srt_gem_gate|<game>|<level>|<key code>"). The function itself lives in
-- init.lua (rules can be evaluated before this script loads); here we just
-- fill SRT_LOCKED from the seed's slot_data so it can answer: a level is
-- locked iff games[<game>].level_keys[<level>] exists this seed.

-- items ---------------------------------------------------------------------

-- Per-level tile overlays: remaining-count + traffic-light background on the
-- level tiles in each game's Overview. Unlocked only (locked tiles stay
-- clean); green = all checks done ("0"), amber = partial, red = none yet.
-- NOTE: overlays are visual-only (autosave persists item states, not
-- overlay payloads); they are recomputed once per frame when queued:
-- the clear handler backfills 82+ locations, onLocation fires per new check —
-- queueing coalesces them into one rebuild next frame.
local COLORS = { done = "#2ecc40", partial = "#ffdc00", none = "#ff4136" }
local OVERLAY_QUEUED = false

local function queue_overlays()
    OVERLAY_QUEUED = true
end

local function flush_overlays()
    if not OVERLAY_QUEUED then
        return
    end
    OVERLAY_QUEUED = false
    local ok, err = pcall(function()
        Tracker.BulkUpdate = true
        for game, levels in pairs(LEVEL_SECTIONS) do
            for level, data in pairs(levels) do
                local total = #data.refs
                local cleared = 0
                for _, ref in ipairs(data.refs) do
                    local sec = Tracker:FindObjectForCode(ref)
                    if sec and sec.ChestCount > 0
                            and sec.AvailableChestCount == 0 then
                        cleared = cleared + 1
                    end
                end
                local obj = Tracker:FindObjectForCode(data.tile)
                if obj then
                    if not obj.Active then
                        -- locked: grey tile stays clean; the sprite already
                        -- says "locked", numbers would only add noise
                        obj:SetOverlay("")
                        obj:SetOverlayBackground("")
                    elseif cleared >= total then
                        obj:SetOverlay("0")
                        obj:SetOverlayBackground(COLORS.done)
                    elseif cleared > 0 then
                        obj:SetOverlay(tostring(total - cleared))
                        obj:SetOverlayBackground(COLORS.partial)
                    else
                        obj:SetOverlay(tostring(total))
                        obj:SetOverlayBackground(COLORS.none)
                    end
                else
                    print(string.format(
                        "SRT-AP: no tile item for %s (data.tile=%s)",
                        level, tostring(data.tile)))
                end
            end
        end
        Tracker.BulkUpdate = false
    end)
    if not ok then
        Tracker.BulkUpdate = false
        print("SRT-AP: overlay update failed: " .. tostring(err))
    end
end

local function advance(entry, item_id)
    local obj = Tracker:FindObjectForCode(entry[1])
    if not obj then
        print(string.format("SRT-AP: no tracker item for code %s (id %s)",
                            entry[1], item_id))
        return
    end
    if entry[2] == "count" then
        obj.AcquiredCount = obj.AcquiredCount + 1
    else
        obj.Active = true
    end
    if entry[3] then
        -- level key: jump to the unlocked level's tab
        Tracker:UiHint("ActivateTab", entry[3])
    end
end

local function note_goal_item(item_id)
    if GOAL_REPORTED or not GOALS_PENDING[item_id] then
        return
    end
    GOALS_PENDING[item_id] = nil
    print(string.format("SRT-AP: goal event item %s received", item_id))
    local left = 0
    for _ in pairs(GOALS_PENDING) do
        left = left + 1
    end
    print(string.format("SRT-AP: %d required game(s) still pending", left))
end

local function try_report_goal()
    -- PopTracker's own client (checkd/game) reports GOAL; a tracker must not
    -- race it on a real, mid-play slot. Only send when explicitly allowed.
    if not ALLOW_GOAL_REPORT then
        return
    end
    if GOAL_REPORTED or next(GOALS_PENDING) ~= nil then
        return
    end
    GOAL_REPORTED = Archipelago:StatusUpdate(Archipelago.ClientStatus.GOAL)
    if GOAL_REPORTED then
        print("SRT-AP: all required games complete: reported GOAL")
    else
        print("SRT-AP: StatusUpdate failed (retrying on next item)")
    end
end

local function onItem(index, item_id, item_name, player_number)
    if index <= ITEM_INDEX then
        return
    end
    ITEM_INDEX = index
    local entry = AP_ITEMS[item_id]
    if entry then
        advance(entry, item_id)
    end
    note_goal_item(item_id)
    try_report_goal()
end

-- locations -----------------------------------------------------------------

local function onLocation(location_id, location_name)
    local sec = section(location_id)
    if sec then
        sec.AvailableChestCount = sec.AvailableChestCount - 1
    end
    queue_overlays()
end

local function onScout(location_id, location_name, item_id, item_name, item_player)
    -- TODO: show scout info (optional).
end

-- connect / clear -----------------------------------------------------------

local function reset_items()
    for _, entry in pairs(AP_ITEMS) do
        local obj = Tracker:FindObjectForCode(entry[1])
        if obj then
            if entry[2] == "count" then
                obj.AcquiredCount = 0
            else
                obj.Active = false
            end
        end
    end
end

local function onClear(slot_data)
    SLOT_DATA = slot_data
    ITEM_INDEX = -1
    GOAL_REPORTED = false
    PLAYER_ID = Archipelago.PlayerNumber or -1
    reset_items()
    local included = type(slot_data) == "table"
        and type(slot_data.included_games) == "table"
        and slot_data.included_games or {}
    print(string.format("SRT-AP: slot %s included games: %s",
        tostring(slot_data and slot_data.slot),
        table.concat(included, ", ")))
    -- reset all known location sections
    for _, entry in pairs(AP_MAPS) do
        local obj = Tracker:FindObjectForCode("@" .. entry[1] .. "/" .. entry[2])
        if obj then
            obj.AvailableChestCount = obj.ChestCount
        end
    end
    -- goal items: required games' goal_location selects the event; only ids
    -- > 0 are verifiable (goal_watch.lua semantics).
    GOALS_PENDING = {}
    local required = type(slot_data) == "table"
        and type(slot_data.required_games) == "table" and slot_data.required_games
        or {}
    local games = type(slot_data) == "table" and type(slot_data.games) == "table"
        and slot_data.games or {}
    -- levels locked this seed: game -> {level -> true}; empty when no locks.
    -- srt_gem_gate (init.lua) reads this to color the Gems board.
    SRT_LOCKED = {}
    for gkey, g in pairs(games) do
        local keys = type(g) == "table" and g.level_keys or nil
        local set = {}
        if type(keys) == "table" then
            for level in pairs(keys) do
                set[level] = true
            end
        end
        SRT_LOCKED[gkey] = set
    end
    for _, key in ipairs(required) do
        local g = games[key]
        local gid = type(g) == "table" and g.goal_location or nil
        if type(gid) == "number" and gid > 0 then
            local candidates = AP_GOALS[key] or {}
            for item_id, row in pairs(candidates) do
                if row.loc == gid then
                    GOALS_PENDING[item_id] = true
                    print(string.format(
                        "SRT-AP: goal %s -> wait for item %s (%s)",
                        key, item_id, row.name))
                end
            end
        end
    end
    local n_goals = 0
    for _ in pairs(GOALS_PENDING) do
        n_goals = n_goals + 1
    end
    if n_goals > 0 then
        print(string.format("SRT-AP: tracking %d goal item(s)", n_goals))
    elseif #required > 0 then
        print(string.format(
            "SRT-AP: %d required game(s) but no verifiable goal_location " ..
            "(counter goal) — goal reporting off", #required))
    end
    print(string.format("SRT-AP: slot connected player=%s seed=%s",
        PLAYER_ID, tostring(Archipelago.Seed)))
    -- backfill: everything the server already has
    if Archipelago.CheckedLocations then
        local n_checked = 0
        for _, location_id in pairs(Archipelago.CheckedLocations) do
            local sec2 = section(location_id)
            if sec2 then
                sec2.AvailableChestCount = sec2.AvailableChestCount - 1
            end
            n_checked = n_checked + 1
        end
        print(string.format(
            "SRT-AP: backfilled %d checked location(s)", n_checked))
    end
    queue_overlays()
    -- TODO: item backlog backfill (server does not replay items on reconnect
    -- with the same session; on a fresh PopTracker start the counters start
    -- empty — Sync() backfill needs a full item scan, keep manual for now).
    try_report_goal()
end

Archipelago:AddClearHandler("clear", onClear)
Archipelago:AddItemHandler("item", onItem)
Archipelago:AddLocationHandler("location", onLocation)
if Archipelago.AddScoutHandler then
    Archipelago:AddScoutHandler("scout", onScout)
end

-- Level follow: the game's mod bounces the slot's current level (region)
-- targeted at this slot ({type="SRTLevel", level="<region>"}); activate that
-- level's tab. Region names are the generated tab titles (world/data group
-- names); an unknown region (e.g. Dragon Shores, no tab) just no-ops.
local function onBounced(packet)
    local data = type(packet) == "table" and packet.data or nil
    if type(data) ~= "table" or data.type ~= "SRTLevel" then
        return
    end
    if type(data.level) ~= "string" then
        return
    end
    print("SRT-AP: level -> " .. data.level)
    Tracker:UiHint("ActivateTab", data.level)
end
if Archipelago.AddBouncedHandler then
    Archipelago:AddBouncedHandler("srtlevel", onBounced)
else
    print("SRT-AP: PopTracker too old for bounces — level follow disabled")
end

if ScriptHost.AddOnFrameHandler then
    ScriptHost:AddOnFrameHandler("srt_overlay_flush", flush_overlays)
end