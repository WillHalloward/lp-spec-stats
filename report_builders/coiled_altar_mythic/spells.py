"""Names the Mythic page keys off. Names, not ids: the report's own ability
table resolves them, so a patch that re-issues ids does not break the build.

Several names cover more than one id (a cast, its damage and a debuff share a
name), so the analysis always narrows by event type as well as by name.
"""

ENCOUNTER_ID = 3429

PHASES = {1: "P1", 2: "P2", 3: "INT", 4: "P3"}

# --- spinning axes ----------------------------------------------------------
AXE = "Axegrinder"
# Ticks land every 0.25s while you stand in an axe; a gap longer than this
# starts a new axe (the tick-gap histogram has 6009 gaps at 0.25s, 265 at 0.5s
# and a long flat tail after 0.75s).
AXE_BOUT_GAP_MS = 750
# Time-in-phase buckets for the night's exposure curve. Axes pile up through
# stage one, so a later second of the phase is worth more ticks than an early
# one and a raw per-minute rate would just track how long the pull lasted.
AXE_BUCKET_MS = 10_000
# A pull's stage needs this many raid-minutes alive before its rate is drawn or
# trended: a pull that wiped two seconds into stage two has no rate worth reading.
AXE_MIN_ALIVE_MIN = 5

# --- orbs -------------------------------------------------------------------
GREEN = "Volatile Venom"  # carrying a normal orb
PURPLE = "Mutagenic Venom"  # carrying a Virulent Mutation
RUPTURE = "Venom Rupture"
DELUGE = "Toxic Deluge"
# An explosion this close to a Toxic Deluge cast is a Mutation left on the
# ground (it blows on the cast), not one carried into another orb.
DELUGE_GRACE_MS = 1500
# A Virulent Mutation touching another orb puts 20 Rupture stacks on everyone at
# once. A Sever never adds more than 10 (the push at the end of P1), so any
# single jump of this many stacks is an explosion.
EXPLOSION_STACKS = 15
# Holders counted around an explosion: anyone carrying a purple, or who put
# one down, this long before it went off.
EXPLOSION_HOLD_MS = 3000

# A carrier whose orb debuff comes off within this of an explosion's first
# Rupture stack lost it in that explosion. Not proof of contact (see
# Analysis._set_off): co-listed carriers stand 16-88 yd apart.
SET_OFF_MS = 30
# A carried orb drops by itself after five seconds; one that drops on the
# explosion's millisecond at full time was put down on top of another orb.
ORB_EXPIRE_MS = 4950
# A player's position is read from the nearest hit they took, within this.
POS_MAX_AGE_MS = 400

# --- frontals ---------------------------------------------------------------
FRONTALS = ("Sever", "Soul Sever", "Blighted Sever")
# Soul Sever leaves a DoT under the same name that ticks every 2s for ~48s,
# and WCL does not flag those ticks as `tick`. They are not frontal hits.
FRONTAL_DOTS = {1312630}
# Rupture stacks from a frontal land this soon after its cast.
FRONTAL_GRACE_MS = 1500

# --- Guillotine -------------------------------------------------------------
GUILLOTINES = ("Guillotine", "Grim Guillotine")
EXECUTIONS = {"Guillotine": "Execution", "Grim Guillotine": "Grim Execution"}

# --- stage two shield and adds ---------------------------------------------
VEIL = "Veil of Twilight"
NIGHTFALL = "Eternal Nightfall"
USURPER = "Hex Lord Malacrass"
SERPENT = "Zul'jan"
SPIRITCACKLE = "Spiritcackle"
SOULCOILER = "Spiteful Soulcoiler"
SPIRIT_SHIELD = "Spirit Shield"
DREADMARCH = "Dreadmarch"

# --- the resets -------------------------------------------------------------
# Cast by Malacrass about ten seconds into a pull that is being reset. Not the
# Guillotine failure (that is Execution, at 48s/133s); it lands before any
# Guillotine exists. Pulls carrying it are left out of every rate.
RESET = "Unworthy"
RESET_MAX_SEC = 35

# --- wipes ------------------------------------------------------------------
# Same rule as the Twin Fangs page: a wipe starts at the first death of the
# first run of CASCADE_N deaths inside CASCADE_S seconds. Nothing after it counts.
CASCADE_N = 4
CASCADE_S = 8.0
# ...and only if the deaths then keep coming with no gap this long until the
# pull ends. Pull 9 lost four to the first Guillotine at 48s and played on to
# 133s; without this it was cut at 48s.
RECOVER_S = 20.0

# --- the intermission -------------------------------------------------------
# Zul'jan comes back on 1 HP and regenerates 2% a second. Each Fragment of
# Malacrass is body-blocked (SPIRIT ERASURE on every living player) or reaches
# him (RECLAIM: 10% of his health, plus a heal on Malacrass, one heal on each).
REGEN = "Ghastly Regeneration"
RECLAIM = "Reclaim Essence"
INT_AURA = "Spirit Erasure"
# A volley counts as fragments only when it lands on this many players at once.
GHOST_BLAST_MIN_TARGETS = 8
from report_builders.coiled_altar.spells import LUST  # noqa: E402,F401

# --- what ended each pull ---------------------------------------------------
# Deaths grouped by the mechanic behind the killing blow. Anything not listed
# shows under its own ability name.
DEATH_GROUPS = {
    "Venom Rupture": "Orbs and venom",
    "Mutagenic Venom": "Orbs and venom",
    "Volatile Venom": "Orbs and venom",
    "Coalesced Venom": "Orbs and venom",
    "Toxic Deluge": "Orbs and venom",
    "Noxious Ground": "Orbs and venom",
    "Axegrinder": "Spinning axes",
    "Sever": "Frontals",
    "Soul Sever": "Frontals",
    "Blighted Sever": "Frontals",
    "Guillotine": "Guillotine",
    "Execution": "Guillotine",
    "Grim Guillotine": "Guillotine",
    "Grim Execution": "Guillotine",
    "Eternal Nightfall": "Shield not broken",
    "Malevolent Resonance": "Ghosts touching (Malevolent Resonance)",
    "Gravebound": "Souls (Gravebound)",
    "Spirit Erasure": "Intermission fragments (Spirit Erasure)",
}
# Deaths with no killing ability are people going off the platform.
FALL_MARCH = "Walked off by Dreadmarch"
FALL_CAUGHT = "Caught by a ghost, walked off"
FALL_KNOCKBACK = "Knocked off at the handover"
FALL_OTHER = "Fell or jumped off"
# An explosion or a Guillotine miss counts as the wipe's cause from this long
# before its first death to the end of its opening (WIPE_OPEN_MS): a Grim
# Guillotine missed seven seconds into a collapse still kills twelve.
WIPE_LEAD_MS = 2500
# The opening of the wipe that decides its cause: deaths this long after the
# first one.
WIPE_OPEN_MS = 8000
# A wipe that opens with this share of falls nobody was marched or caught into
# is the raid jumping to reset.
RESET_FALL_SHARE = 0.5
