"""Spell, actor and phase names the report keys off.

Names rather than ids: Blizzard re-issues spell ids between patches, and the
report's own ability table gives us the ids for whatever names are in this log.

The encounter is two bosses. Zul'jan owns stages one and three; Hex Lord
Malacrass arrives in stage two and both are up for stage three.
"""

ENCOUNTER_ID = 3429
ENCOUNTER = "The Coiled Altar"

SERPENT = "Zul'jan"
USURPER = "Hex Lord Malacrass"

# Phase ids as Warcraft Logs reports them. 3 is flagged isIntermission.
PHASES = {1: "P1", 2: "P2", 3: "INT", 4: "P3"}
PHASE_NAMES = {
    "P1": "Stage One: Serpent's Bargain",
    "P2": "Stage Two: Usurper's Reprisal",
    "INT": "Intermission: The Claimed Vessel",
    "P3": "Stage Three: Coiled Union",
}
ORB_PHASES = ("P1", "P3")

# --- the orbs -------------------------------------------------------------
# Carriers pick an orb up (ORB_CARRY, a flat 5s), drop it in the tank frontal,
# and CLEAVE detonates everything sitting in it. Each orb detonated puts one
# stack of ORB_BURST on the raid; ORB_PULSE is the per-orb aura ticking the
# whole time an orb is alive.
ORB_CARRY = "Volatile Venom"
ORB_BURST = "Venom Rupture"
ORB_PULSE = "Coalesced Venom"
ORB_NPC = "Coalesced Venom Stalker"
CLEAVE = ("Sever", "Blighted Sever")  # stage one / stage three frontal

# --- the veil gate --------------------------------------------------------
# Malacrass shields himself and starts a 15s channel. Break the shield or the
# channel resolves and deletes the raid.
VEIL = "Veil of Twilight"
NIGHTFALL = "Eternal Nightfall"
NIGHTFALL_WINDOW_SEC = 15.0
HEAL_ABSORB = "Suffocating Darkness"
CIRCLES = "Gloombomb"

# --- mind control ---------------------------------------------------------
# Both mind controls log as the SAME debuff. Malacrass casts it on 4-6 people at
# once, and that one is unavoidable. A ghost catching somebody applies it too, to
# one person, with no cast anywhere near and always as that player's fixation
# ends. That difference is the only way to tell the two apart, and they mean
# opposite things, so the report splits them.
MARCH = "Dreadmarch"
# How close to a Malacrass cast an application has to be to count as cast-sourced.
MARCH_CAST_GRACE_MS = 2500
# How close to a fixation ending a lone application has to be to count as a catch.
MARCH_TOUCH_GRACE_MS = 1500
# Dreadmarch is an absorb shield and the possession lasts until it is gone. It
# does not expire and cannot be stunned off. Damage the shield eats produces no
# damage event at all, only an `absorbed` record in the healing stream, so that
# is where depletion has to be measured. Whichever way it ends, two more ghosts
# emerge from the possessed player, so every catch feeds the next one.
MARCH_ABSORB = 494352
MARCH_SPAWNS = 2
FIXATE = "Unnerving Fixation"
GHOST = "Manifestation of Dread"
GHOST_IMMUNE = "Unassailable"
# A mind control breaks on roughly half the victim's health, so the raid
# damages its own. Support effects that legitimately cross the raid and are
# not a break attempt.
NOT_A_BREAK = {
    "Blessing of Sacrifice",
    "Refraction",
    "Anti-Magic Zone",
    "Fel Armor",
    "Set Fire to the Pain",
    "Light of the Martyr",
    "Spirit Link Totem",
    "Leech",
    "Vampiric Embrace",
    "Pain Suppression",
}
# Hard crowd control aimed at a mind-controlled ally, and the ground-targeted
# AoE stops used the same way (those log against Environment, not a player).
CC_TARGETED = {
    "Death Grip",
    "Hammer of Justice",
    "Chains of Ice",
    "Storm Bolt",
    "Holy Word: Chastise",
    "Repentance",
    "Imprison",
    "Fel Eruption",
    "Asphyxiate",
    "Strangulate",
    "Grapple Weapon",
    "Mighty Bash",
}
CC_GROUND = {
    "Ring of Peace",
    "Leg Sweep",
    "Shadowfury",
    "Blinding Light",
    "Shockwave",
    "Capacitor Totem",
    "Thunderstorm",
    "Typhoon",
    "Ursol's Vortex",
    "Sigil of Chains",
    "Gorefiend's Grasp",
    "Incapacitating Roar",
    "War Stomp",
}

# --- the intermission burn window ----------------------------------------
# Malacrass shields himself to 99% and binds the serpent, who takes double
# damage and heals hard. This is the lust window.
BOSS_SHIELD = "Deathguard"
SOULBIND = "Soulbinding"
REGEN = "Ghastly Regeneration"
# Small ghosts walk at the serpent all through the intermission. Body-block one
# and it is destroyed, at the cost of a raid-wide blast (INT_AURA fires once per
# ghost, hitting everyone at once); let one reach him and it is RECLAIM instead,
# healing a fixed slab of the resurrection. Every ghost is one or the other, so
# blocks and reclaims sum to roughly the same total every pull.
RECLAIM = "Reclaim Essence"
# A blast counts as one ghost when it lands on at least this many people at
# once. A ghost blast is raid-wide, so a smaller cluster is somebody's DoT.
GHOST_BLAST_MIN_TARGETS = 8
MERGED = "Soulbound"

LUST = {
    "Bloodlust",
    "Heroism",
    "Time Warp",
    "Fury of the Aspects",
    "Primal Rage",
    "Drums of Fury",
    "Drums of the Mountain",
    "Drums of the Maelstrom",
    "Drums of Deathly Ferocity",
    "Feral Hide Drums",
    "Drums",
    "Ancient Hysteria",
}

# --- everything else that kills people ------------------------------------
RAID_AURA = "Dreadful Presence"  # stage two, ramps until the phase ends
INT_AURA = "Spirit Erasure"  # intermission survival tax
TANK_STACK = "Gravebound"

# Defensive tiers, healthstones and potions are class-generic rather than
# encounter-specific, so they are shared with the Ula'tek builder instead of
# being kept in two places that can drift apart.
from report_builders.ulatek.spells import (  # noqa: E402,F401
    MAJOR,
    MINOR,
    EXTERNAL,
    HEALTHSTONES,
    HEALTH_POTIONS,
)

# A few buttons are a defensive for one spec and a damage cooldown for another.
# Metamorphosis mitigates for Vengeance and is pure throughput for Havoc, so
# counting it for a Havoc demon hunter inflates them by a cooldown a minute.
NOT_DEFENSIVE_FOR_SPEC = {
    "Metamorphosis": {"Havoc"},
}

# The shared EXTERNAL set mixes two different things: cooldowns handed to one
# named player, and cooldowns dropped on the whole raid. Both are worth counting,
# but calling a Spirit Link Totem an "external given" credits somebody with
# something they did not do for anyone in particular. These log against
# Environment rather than a player, which is the giveaway. Split out here rather
# than in the shared set, so the other report's numbers do not move.
RAID_WIDE = {
    "Aura Mastery",
    "Spirit Link Totem",
    "Darkness",
    "Anti-Magic Zone",
    "Zephyr",
    "Barrier of Faith",
    "Stone Bulwark Totem",
    "Rallying Cry",
    "Devotion Aura",
    "Power Word: Barrier",
    "Salvation",
    "Vampiric Embrace",
    "Revival",
}

# Tanks press mitigation on cooldown as part of their rotation, which buries the
# signal this section is after: did somebody press a save when the fight asked
# for one. They are counted everywhere else and left out here.
MITIGATION_SKIP_ROLES = {"Tank"}

DIFFICULTY = {1: "LFR", 3: "Normal", 4: "Heroic", 5: "Mythic"}
