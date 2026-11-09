"""Spell and actor ids for Mythic Twin Fangs, as they appear in the log.

Read off report gfvXpCWVRj43anTH. Where one name maps to several ids, the
comment says which is which. An id that turns out wrong shows up as an empty
chart or a zero count rather than an error, so check against a log first.
"""

# --- boss casts: the fixed script every pull runs to ---
BLOOD_TORRENT = 1303230  # Ithraz; opens each globule wave (with Caustic Deluge)
CAUSTIC_DELUGE = 1289192  # Vexhul's cast that opens the wave
GLOBULE_DROP = 1289994  # one Caustic Deluge 'cast' per globule dropped: 15 a wave on Mythic
STONE_BREAKER = 1288538  # Ithraz; three tank soaks
ROUSE = 1308356  # Ithraz; ten Broodlings
EMERGENCE = 1291404  # Vexhul; three Spawn of Vexhul
COILING_ICHOR = 1290809
STIR = 1290956  # Stir the Depths, the waves
FEAST = 1290516  # Ravenous Feast, three smashes
FEAST_HIT = 1290662  # a smash landing on a player; a smash with too few in it hits the whole raid
SANGUINE_STORM = 1306872
VILE_FLOOD = 1294293  # the Submerge beam

# --- adds ---
VISCERAL_BURST = 1308385  # Broodling cast; a completed cast is a missed kick
CORROSIVE_SPIT = 1291478  # Spawn of Vexhul cast

# --- Eternal Venom and what adds a stack ---
ETERNAL_VENOM = 1290336
GLOBULE_SOAK = 1289201  # one player walks into a globule; the 'cast' targets the soaker
GLOBULE_BURST = 1290338  # an unsoaked globule exploding on the whole raid
BARBED_BULWARK = 1303378  # the shield on each globule; one actor instance per globule
FEASTED = 1310096  # the debuff a Feast soaker gets
TAINTED_BLOOD = 1310102  # heal absorb on players standing in a blood fount

# Stir the Depths: the wave debuff, applied with its stack (rarely with damage)
STIR_DEBUFF = 1292807

# stack sources, by the damage (or, for waves, the debuff) that lands with the stack
SPIT_TARGET = 1293979  # Corrosive Spit debuff on the player the beam is locked onto
EV_SOURCES = {
    GLOBULE_SOAK: "soak",
    GLOBULE_BURST: "burst",
    1308122: "emergence",  # Venomous Emergence, one stack each, unavoidable
    1293295: "spit",  # Corrosive Spit from a snake
    1292807: "wave",  # Stir the Depths wave
    1294605: "flood",  # Vile Flood beam
    1289994: "deluge",  # Caustic Deluge: a globule landing on someone (GLOBULE_DROP)
    1289237: "deluge",  # Caustic Deluge on the tank; rarely the hit a stack lines up with
}
EV_LABEL = {
    "soak": "globule soaked",
    "burst": "globule exploded",
    "emergence": "Venomous Emergence",
    "spit": "Corrosive Spit on its target",
    "cleave": "Corrosive Spit cleave",
    "wave": "wave",
    "flood": "Vile Flood",
    "deluge": "globule landed on them",
    "other": "other",
}

# --- actors (game ids, stable across reports) ---
BROODLING = "Broodling of Ithraz"
SPAWN = "Spawn of Vexhul"
BULWARK = "Barbed Bulwark"

# The ten spots a Broodling surfaces at, in map units (yards * 100), read off
# where each one first took damage. Five per side; numbered outer to inner, so
# L1 and R1 are the far ends of the arc and L5 / R5 sit between the bosses.
SPOTS = {
    "L1": (-3706, 65476),
    "L2": (-3248, 66216),
    "L3": (-3040, 67700),
    "L4": (-2628, 68418),
    "L5": (-606, 69236),
    "R5": (561, 69198),
    "R4": (2534, 68321),
    "R3": (3004, 67592),
    "R2": (3333, 66190),
    "R1": (3819, 65373),
}
SPOT_RADIUS = 700  # a Broodling further than 7 yd from every spot was moved first
# Where the bosses stood when SPOTS were read. The spots move with the bosses
# (after Submerge they surface in a corner), so a Broodling is placed in the
# frame the two bosses make at its Rouse, not in room coordinates.
BOSSES_AT_SPOTS = {"Vexhul": (-1616, 69157), "Ithraz": (1586, 69132)}

# Interrupt cooldowns in seconds, for "who had a kick ready". Thunderstorm is
# left out: it interrupts only through its knockback, and is not a kick.
KICK_CD = {
    6552: 15,  # Pummel
    116705: 15,  # Spear Hand Strike
    2139: 24,  # Counterspell
    96231: 15,  # Rebuke
    147362: 24,  # Counter Shot
    57994: 12,  # Wind Shear
    19647: 24,  # Spell Lock (pet)
    119910: 24,  # Spell Lock (command demon)
    183752: 15,  # Disrupt
    1766: 15,  # Kick
    47528: 15,  # Mind Freeze
    106839: 15,  # Skull Bash
    187707: 15,  # Muzzle
    351338: 20,  # Quell
    78675: 60,  # Solar Beam
    15487: 30,  # Silence
}

# Crowd control that strips a Barbed Bulwark, by debuff name on the globule.
SHIELD_CC = {
    "Capacitor Totem", "Blinding Light", "Incapacitating Roar", "Shockwave", "Howl of Terror",
    "Dragon's Breath", "Psychic Scream", "Hammer of Justice", "Storm Bolt", "Leg Sweep",
    "Chaos Nova", "Intimidation", "Kidney Shot", "Holy Word: Chastise", "Mortal Coil",
    "Mass Entanglement", "Ring of Peace", "Sigil of Misery", "Fear", "Intimidating Shout",
    "Cheap Shot", "Mighty Bash", "Sundering", "Static Charge", "Paralysis", "Polymorph",
    "Repentance", "Blind", "Sap", "Gouge", "Shadowfury", "Thunderstorm", "Binding Shot",
    "Imprison", "Sleep Walk", "Landslide", "Deep Breath", "Typhoon", "Ursol's Vortex",
    "Solar Beam", "Wild Charge", "Disorienting Roar", "Abomination Limb", "Asphyxiate",
    "Blinding Sleet", "Gorefiend's Grasp",
}
