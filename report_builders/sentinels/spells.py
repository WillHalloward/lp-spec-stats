"""Spell and actor names the report keys off.

Names rather than ids: Blizzard re-issues spell ids between patches, and the
report's own ability table gives us the ids for whatever names are in this log.
"""

# NPCs, by the gameID Warcraft Logs reports for them (name is the fallback).
BREATH = ("Breath of Ula'tek", 258557)  # the green boss
BLOOD = ("Blood of Ula'tek", 258558)  # the red boss
SLIME = ("Venom Coagulation", 260766)  # the add Breath spawns

# Encounter-wide
STASIS = "Vitriolic Stasis"  # the intermission; the boss buff and the heal share the name
DOMINANCE = "Ula'tek's Dominance"  # the bosses within 25 yards: 99% less damage taken
BERSERK = "Berserk"
HELICAL = "Helical Toxins"  # the intermission puzzle debuff
BURST = "Cultivated Burst"  # what a wrong pairing costs
MARK_ACID = "Mark of Acid"  # stacked by Breath on everyone within 40 yards
MARK_BLOOD = "Mark of Blood"  # stacked by Blood on everyone within 40 yards

# Breath of Ula'tek
DROPLETS = "Toxic Droplets"  # the cast, and the soak damage when one is run over
NOXIOUS = "Noxious Blast"  # a droplet nobody ran over, hitting the whole raid
COAGULATION = "Venom Coagulation"
CONTAMINATE = "Contaminate"  # the slime's raid-wide pulse
LIVING_VENOM = "Living Venom"
SLAM = "Empowering Slam"

# Blood of Ula'tek
MIASMA = "Unstable Miasma"
BLIGHTED = "Blighted Blood"
BLOOD_VENOM = "Blood Venom"  # the pools Blighted Blood leaves; standing in one applies it
INJECTION = "Bloodvenom Injection"

# Mythic
PROTOVENOM = "Shifting Protovenom"
ERUPTION = "Protovenom Eruption"

BERSERK_AT = 420  # seconds; every pull that lived this long saw both bosses cast it

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
}

# Personal cooldowns that exist to survive something.
MAJOR = {
    "Anti-Magic Shell",
    "Icebound Fortitude",
    "Vampiric Blood",
    "Lichborne",
    "Blur",
    "Barkskin",
    "Obsidian Scales",
    "Renewing Blaze",
    "Exhilaration",
    "Aspect of the Turtle",
    "Survival of the Fittest",
    "Ice Block",
    "Ice Cold",
    "Greater Invisibility",
    "Fortifying Brew",
    "Divine Shield",
    "Divine Protection",
    "Shield of Vengeance",
    "Cloak of Shadows",
    "Evasion",
    "Astral Shift",
    "Unending Resolve",
    "Dark Pact",
    "Survival Instincts",
    "Netherwalk",
    "Dispersion",
    "Desperate Prayer",
    "Rallying Cry",
    "Shield Wall",
    "Die by the Sword",
    "Celestial Brew",
    "Dampen Harm",
    "Diffuse Magic",
    "Touch of Karma",
    "Ardent Defender",
    "Guardian of Ancient Kings",
    "Metamorphosis",
    "Demon Spikes",
}
# Short-cooldown or rotational mitigation. Counted, but not as "did they press a save".
MINOR = {
    "Feint",
    "Crimson Vial",
    "Prismatic Barrier",
    "Blazing Barrier",
    "Ice Barrier",
    "Alter Time",
    "Frenzied Regeneration",
    "Purifying Brew",
    "Dancing Rune Weapon",
    "Rune Tap",
    "Renewal",
    "Expel Harm",
    "Black Ox Brew",
}
# Cast on somebody else.
EXTERNAL = {
    "Ironbark",
    "Blessing of Protection",
    "Blessing of Sacrifice",
    "Lay on Hands",
    "Spirit Link Totem",
    "Aura Mastery",
    "Darkness",
    "Anti-Magic Zone",
    "Zephyr",
    "Pain Suppression",
    "Guardian Spirit",
    "Life Cocoon",
    "Barrier of Faith",
    "Stone Bulwark Totem",
}

HEALTHSTONES = {"Healthstone", "Demonic Healthstone", "Soulburn: Healthstone"}
HEALTH_POTIONS = {
    "Concentrated Silvermoon Health Potion",
    "Silvermoon Health Potion",
    "Potent Healing Potion",
    "Cavedweller's Delight",
    "Dreamwalker's Healing Potion",
    "Refreshing Healing Potion",
}

DIFFICULTY = {1: "LFR", 3: "Normal", 4: "Heroic", 5: "Mythic"}
