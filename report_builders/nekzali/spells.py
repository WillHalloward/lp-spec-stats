"""The ability names this report keys off.

Names rather than ids, because Blizzard re-issues ids between patches and this
encounter already ships four separate ids called "Immortal Coil". The report's
own ability table resolves whatever names are in that log; `Analysis.ids_named`
returns every id behind a name, so a stage-split aura or a re-issued spell
needs no change here.
"""

# --- the well ---------------------------------------------------------------
# Entering applies Immortal Coil, which ramps through three ids before it bites.
IMMORTAL_COIL = "Immortal Coil"
# Applied on leaving the well. 60s, +300% damage from the well and Immortal Coil.
SOUL_EXHAUSTION = "Soul Exhaustion"
# Raid-wide pull + shadow damage for as long as the Drowned Echo lives.
GRASPING_DEPTHS = "Grasping Depths"
# Beams inside the well.
SWIRLING_SPIRIT = "Swirling Spirit"
# The well itself: what kills people standing in it outside a dive.
SOULCOIL_WELL = "Soulcoil Well"
# Interruptible. Ejects the dive team and applies Soulcoiled.
SOULCOILERS_CURSE = "Soulcoiler's Curse"

# --- phases -----------------------------------------------------------------
RITUAL_OF_AWAKENING = "Ritual of Awakening"
ECHO_OF_JAWAE = "Echo of Jawae"
# Stage Two: non-dropping Soulcoil Rite, silences, repositioned puddles.
INVOKE = "Invoke"

# --- adds -------------------------------------------------------------------
RESTLESS_AMANI = "Restless Amani"

LUST = ("Bloodlust", "Heroism", "Time Warp", "Fury of the Aspects",
        "Primal Rage", "Ancient Hysteria", "Drums of Rage")

# Soul Exhaustion's duration, seconds. Read off the log when it can be, this is
# the fallback for a pull where nobody's debuff runs its full course.
EXHAUSTION_SECONDS = 60.0

# An overlap shorter than this is the aura falling off a fraction after the
# debuff lands, not somebody walking back in while locked out.
OVERLAP_FLOOR_SECONDS = 1.2

# Two dives whose auras are this close are one dive split by a stage change.
DIVE_MERGE_SECONDS = 0.3

# A gap this long in the Grasping Depths damage stream ends an Echo's window.
WINDOW_GAP_SECONDS = 4.0

# Divers entering within this window of each other are one wave.
WAVE_SECONDS = 14.0

# An early entry taken with this many already dead is the wipe dragging bodies
# into the water, not a rotation call.
COLLAPSE_DEATHS = 5
