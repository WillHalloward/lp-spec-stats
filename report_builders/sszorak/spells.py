"""Spell ids for Sszorak (The Venomous Abyss), as the Mythic log writes them."""

ENCOUNTER = 3420

# --- Apex Predator: the five-cast tank combo (2 Ravage, 2 Mutilate, 1 Tempest)
RAVAGE_CAST = 1277002
RAVAGE_HIT = 1277101  # the frontal itself; anyone but the tank in it is a mistake
RAVAGE_VULN = 1277105  # 600% vulnerability on the tank
MUTILATE_CAST = 1277027
MUTILATE_HIT = 1285999  # the soak
MUTILATED_GASH = 1285998  # the bleed the soak leaves (damage)
MUTILATED_GASH_DEBUFF = 1277051
TEMPEST_CAST = 1287072
TEMPEST = 1287083  # tornado hit (no tick flag) and its DoT (tick flag); debuff stacks

# --- Serpent's Fury (Mythic): the mark that 14 have to soak before 100 rage
SERPENTS_FURY = 1305621  # debuff on the marked player; it drops when the pop goes off
VIRULENCE_DEBUFFS = (1297707, 1299899)  # the two halves of the soak group (+ and x lines)
VIRULENCE_LINE = 1312189  # the lines when the debuff runs out
VIRULENCE_HIT = 1300089  # To the Slaughter's charge
UNBOUND_FEROCITY = 1296898  # the boss reached 100 rage: 500% damage until the raid dies

# --- Venomous Surge -> Viscous Cyst
SURGE_CAST = 1305959
SURGE_DEBUFF = 1305963  # two marked players, ten seconds
SURGE_DOT = 1312156
SURGE_BURST = 1306120  # raid-wide when each mark runs out and the cyst lands
VISCOUS_CYST = 1287205  # pop = the hit without a tick flag (knockback); the DoT ticks after

# --- Raging Crosswinds: eight players knocked up along their arrow
CROSSWINDS_DEBUFFS = (1285425, 1285453, 1297111, 1297096)  # the four directions
CROSSWINDS_DOT = 1312219  # ticks on the eight while they wait
CROSSWINDS_KNOCK = 1285616  # the launch
TURBULENT_GUSTS = 1285447  # the knock-up itself; a cancelled pair drops it inside a second

# --- Intermission
DIG_IN = 1286033

# --- floor
CAUSTIC_CLAWS = 1305998
CAUSTIC_RESIDUE = 1296667
ULATEKS_PRESENCE = 1285965  # raid-wide rot every two seconds
CORRODING_VENOM = 1282873
MELEE = 1
FALLING = 3

# Killing blows grouped by the mechanic behind them.
DEATH_GROUPS = {
    TEMPEST: "tornado",
    VISCOUS_CYST: "cyst",
    VIRULENCE_LINE: "virulence",
    VIRULENCE_HIT: "virulence",
    SURGE_BURST: "surge",
    SURGE_DOT: "surge",
    MUTILATE_HIT: "mutilate",
    MUTILATED_GASH: "mutilate",
    RAVAGE_HIT: "tank",
    MELEE: "tank",
    CAUSTIC_CLAWS: "floor",
    CAUSTIC_RESIDUE: "floor",
    CROSSWINDS_KNOCK: "crosswinds",
    CROSSWINDS_DOT: "crosswinds",
    ULATEKS_PRESENCE: "rot",
}
