"""Spell and actor names the report keys off.

Names rather than ids: Blizzard re-issues spell ids between patches, and the
report's own ability table gives us the ids for whatever names are in this log.
"""

# NPCs, by the gameID Warcraft Logs reports for them (name is the fallback).
HEART = ("Venomous Heart", 267460)
BOSS = ("Ula'tek", 257758)
VIPER = ("Blightscale Viper", 261915)

WAVE = "Caustic Waves"           # the avoidable wave, cast by the boss
EXPOSE = "Rage of the Shackled"  # opens the heart
LUST = {"Bloodlust", "Heroism", "Time Warp", "Fury of the Aspects", "Primal Rage",
        "Drums of Fury", "Drums of the Mountain", "Drums of the Maelstrom",
        "Drums of Deathly Ferocity", "Feral Hide Drums", "Drums"}

# Personal cooldowns that exist to survive something.
MAJOR = {"Anti-Magic Shell", "Icebound Fortitude", "Vampiric Blood", "Lichborne", "Blur", "Barkskin",
         "Obsidian Scales", "Renewing Blaze", "Exhilaration", "Aspect of the Turtle",
         "Survival of the Fittest", "Ice Block", "Ice Cold", "Greater Invisibility", "Fortifying Brew",
         "Divine Shield", "Divine Protection", "Shield of Vengeance", "Cloak of Shadows", "Evasion",
         "Astral Shift", "Unending Resolve", "Dark Pact", "Survival Instincts", "Netherwalk",
         "Dispersion", "Desperate Prayer", "Rallying Cry", "Shield Wall", "Die by the Sword",
         "Celestial Brew",
         "Dampen Harm", "Diffuse Magic", "Touch of Karma", "Ardent Defender",
         "Guardian of Ancient Kings", "Metamorphosis", "Demon Spikes"}
# Short-cooldown or rotational mitigation. Counted, but not as "did they press a save".
MINOR = {"Feint", "Crimson Vial", "Prismatic Barrier", "Blazing Barrier", "Ice Barrier", "Alter Time",
         "Frenzied Regeneration", "Purifying Brew", "Dancing Rune Weapon", "Rune Tap", "Renewal",
         "Expel Harm", "Black Ox Brew"}
# Cast on somebody else.
EXTERNAL = {"Ironbark", "Blessing of Protection", "Blessing of Sacrifice", "Lay on Hands",
            "Spirit Link Totem", "Aura Mastery", "Darkness", "Anti-Magic Zone", "Zephyr",
            "Pain Suppression", "Guardian Spirit", "Life Cocoon", "Barrier of Faith", "Stone Bulwark Totem"}

HEALTHSTONES = {"Healthstone", "Demonic Healthstone", "Soulburn: Healthstone"}
HEALTH_POTIONS = {"Concentrated Silvermoon Health Potion", "Silvermoon Health Potion",
                  "Potent Healing Potion", "Cavedweller's Delight", "Dreamwalker's Healing Potion",
                  "Refreshing Healing Potion"}

DIFFICULTY = {1: "LFR", 3: "Normal", 4: "Heroic", 5: "Mythic"}
