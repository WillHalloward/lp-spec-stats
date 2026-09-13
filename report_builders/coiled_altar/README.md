# The Coiled Altar prog-night report builder

Turns one Warcraft Logs report into the page served at `/reports/<slug>`.

```bash
export WCL_CLIENT_ID=... WCL_CLIENT_SECRET=...     # same credentials the site uses
python -m report_builders.coiled_altar.build \
    --report 37LT6jAbWXFKqv8x \
    --date 2026-09-12 \
    --night "Piian progression night" \
    --out /tmp/preview.html        # look at it first
python -m report_builders.coiled_altar.build --report <code> ... --publish
```

`--publish` writes `reports/<slug>.html` and adds or replaces the row in
`reports/index.json`; commit and push and Railway serves it. The slug defaults to
`<boss>-<difficulty>-prog-<date>`, so a second night on the same boss lands beside
the first rather than over it — pass `--slug` to overwrite an existing page.

Other flags: `--encounter` and `--difficulty` if the report holds more than one
boss or difficulty (otherwise the most-pulled one wins).

## What it does

1. `fetch.py` pulls what the page needs and caches the raw responses under
   `cache/<report code>/`. A re-run after a template or wording change costs
   nothing; delete the directory to refetch. The cache is large and git-ignored.
   The paging and caching machinery is imported from the Ula'tek builder rather
   than copied — only this encounter's queries live here.
2. `analyze.py` computes the numbers, in the five groups the page is built from:
   pull progress, the orb rotation, the shield gate, the intermission burn
   window, and the falls.
3. `render.py` fills `template.html`: eight JSON payloads for the charts, and one
   token per number the prose says out loud.
4. `build.py` wraps the result in a standalone document and publishes it.

## The encounter, as the builder understands it

Two bosses. Zul'jan owns stages one and three; Hex Lord Malacrass arrives in
stage two, and both are up for stage three. Stage lengths are near-fixed — the
only real variable is how far into stage three a pull survives.

- **Orbs** (stages one and three). Carried via a flat 5s debuff, dropped into the
  tank frontal, detonated by the cleave. Each orb caught stamps one stack of the
  burst DoT on the raid, so *the stack count applied on a frontal is the orb
  count for that frontal* — that identity is what `orbs()` measures. A separate
  per-orb aura pulses the whole time an orb is alive.
- **The shield** (stages two and three). Malacrass gains a fixed absorb and
  starts a 15s channel. Break the absorb and the channel dies; miss and it
  resolves on the raid. The absorb is a flat value, not a percentage, so it is a
  hard DPS gate. `veil()["players"]` attributes the break per raider — every hit
  onto the shield counts, absorbed or not, so the whole hit is credited.
- **The intermission is a resurrection race**, not a survival phase. Stage one
  burns the serpent to nothing on one health pool; the intermission brings it
  back on a second, much larger one. Whatever it reaches when the window closes
  is the handicap carried into stage three, so the key measure is
  `serpent_hp_end` — read off the target resources on damage events, where
  `resourceActor == 2` means the hit points belong to the target. Both pools are
  reported (`pool_one`, `pool_three`); they differ, so max health has to be read
  per phase rather than once.
- **What actually sets that number is the ghosts, not the damage.** Around 41
  small ghosts walk at the serpent during the window. A body-blocked one dies and
  fires `INT_AURA` as a single raid-wide blast (~1.3M of raid damage); one that
  gets through fires `RECLAIM` instead and heals ~21M, three percent of the
  resurrection. Blocks and reclaims sum to roughly the same total every pull,
  which is what proves it is a trade rather than a damage race — and letting one
  past costs about twenty times what blocking it does. Blocks are counted by
  looking for blasts that hit at least `GHOST_BLAST_MIN_TARGETS` players in the
  same tenth of a second, since a ghost blast is raid-wide and anything smaller
  is somebody's DoT.
  `burn()["players"]` compares each raider's own intermission rate to their own
  stage one rate, which is a fairer question than raw damage: it asks who lifts
  when the amp and the haste are up.
- **Two mind controls, one debuff.** This is the subtlest thing in the encounter
  and the easiest to get wrong. Malacrass casts Dreadmarch on 4–6 people at once
  — unavoidable. A ghost catching somebody applies **the same debuff**, to one
  person, with no cast anywhere near and always as that player's fixation ends.
  `march_sources()` reconstructs which is which from those two facts; on the
  first night it split 299 cast against 107 caught and left nothing
  unclassified.

  **Every possession spawns two more ghosts when it drops**, which the log
  confirms at exactly 2.0 new fixations per possessed player (median 3.3s
  later). That is what makes the fixation "waves" waves at all: a four-person
  cast becomes eight ghosts, and a single catch becomes two — so a catch that
  goes unanswered compounds. The collapses on the first night are chains, not
  single mistakes.

  Dreadmarch is an absorb shield of `MARCH_ABSORB` (494,352), and the possession
  lasts until the shield is gone — it does not expire and cannot be stunned off.
  The crowd control keeps the victim away from the edge while the shield is shot
  down; it does not end the possession.

  **Measure the shield from `absorbed` records in the healing stream, never from
  damage events.** Damage the shield eats produces no damage event at all, so a
  damage-stream measurement reports almost nothing and looks like the raid never
  breaks them — it did exactly that here, and concluded "zero broken" when the
  real answer is 346 of 363 (95%), median depletion 494,351 of 494,352. The
  `attackerID` field on those records is who landed the hit, which is how the
  contributor list is built. `sourceID` on those records is the boss that
  *applied* the possession, not a contributor — and that boss also turns up under
  `attackerID` on a handful of records (15 of 363 possessions), so only
  raid-attributed absorb counts toward a break. Raid damage alone reaches the
  full shield in 345 of 363. Pet damage bills to its owner, as everywhere else.

  The split matters because the two mean opposite things. Of the 107 caught, 43
  died within thirty seconds and 39 went over the edge, six to fourteen seconds
  after being caught — while the unavoidable cast accounted for **two** falls all
  night. Reporting them together (as this builder did at first) buries the
  avoidable mechanic inside the unavoidable one and makes the ghosts look
  harmless. Do not merge those buckets again.

## Reading the death numbers

Going off the platform logs with no killing ability, no killer and no damage
event. Three different things produce that signature:

1. a genuine mistake — knocked off, marched off, or stood too close;
2. the wipe reset, which despawns the raid;
3. somebody jumping deliberately to reset a lost pull.

Only the first costs anything, so `edge()` uses two tests together:

- **how much of the raid was already dead** (`RESET_DEAD_SHARE`, 50%), and
- **whether the pull survived it** (`COLLAPSE_TAIL_SEC`, 10s — the kill exempt).

Neither alone is enough. A clock-only filter throws away real knockback deaths,
which land ninety-odd seconds before a pull ends. A dead-share-only filter is a
knife edge in the middle of a collapse: on the first night two people died a
millisecond apart either side of it, one counted and one not, in the same wipe.

Ten seconds is not arbitrary. It clears the collapse without removing a single
knockback or ghost-catch death; fifteen starts eating real knockback deaths. If
you retune it, check those two buckets before and after — they are the ones that
should not move.

On the first night the pair split 190 raw unattributed deaths into **58 falls
that cost something** and 132 during a reset or collapse. The surviving 58 are
almost entirely two mechanics (32 knockback, 22 ghost-catch), which is the point:
once the collapse noise is gone, what is left is what the raid can actually fix.
Do not collapse the two buckets back together to make the headline bigger.

There is deliberately no "fixated" cause. A ghost merely chasing somebody has no
mechanism to push them off — only the possession does — so a fixation with no
possession behind it is a coincidence, not a cause. Checking the five deaths that
bucket originally held found four were collapse and the fifth was a possession
whose shield broke a few seconds before the victim landed, which is why
`CONTROL_GRACE_MS` is 5s rather than 2s: breaking the shield does not save
somebody already over the edge. Everything with no possession is `unexplained`,
and on the first night that is two deaths out of 58.

Two things the log genuinely cannot answer, which the prose is careful not to
claim:

- whether a ghost re-targets when its victim dies. All ghosts share one actor id,
  so a single ghost's target chain cannot be followed. The one usable signal is
  that off-wave fixations (`FIXATE_WAVE_MIN` separates them from spawn waves)
  follow a death far more often than wave fixations do — 38% against 15% on the
  first night. That is suggestive, not conclusive: most off-wave picks follow no
  death at all, so something else triggers them too, and the page says so.
- how much raid damage a single orb detonation causes in isolation — the orb rate
  across a night is too consistent to separate it from everything else ticking.

## Per-player numbers

Both damage checks carry a leaderboard, and two rules keep them honest:

- pet and guardian damage bills to the owner (`owner_of`), so a hunter is not
  split across three bars;
- anything the log never billed to a player is dropped rather than drawn as a
  nameless bar, which also keeps the percentage shares summing over raiders only.

The burn-window multiplier uses per-player baselines, so it is only quoted for
damage roles — a healer doing almost nothing in both phases can post an
arbitrary ratio, and `render._amp` filters to DPS for that reason.

Both leaderboards carry a pull picker. Each player row ships a `by_pull` map
alongside its total, and the page re-ranks and re-computes shares for whichever
pull is selected; the burn rows carry a per-pull multiplier too, since the
stage-one baseline differs pull to pull. `leaderboard()` clears its SVG on every
draw — without that the bars pile up on each change.

## The stage two handover

Stage two ends on a **damage threshold into Malacrass**, not a clock. The damage
dealt by the handover is identical to three significant figures in every pull
(`burn()["gate_spread"]` was 1.00 on the first night, across handovers spanning
half a minute). There is no timer, and the page must not describe one.

So the handover time is purely a choice about stage two damage, and the two
strategies are real:

- **push early** — spend cooldowns in stage two, cross sooner, gain stage three
  time before the enrage, but arrive at the burn window with those cooldowns down;
- **hold** — delay damage deliberately, cross later, bank the cooldowns for the
  burn window, and give up stage three time.

`EARLY_TRANSITION_SEC` (250s) is only the reporting line between the two. It is a
label, not a mechanic; move it if a later night sits differently. Do not present
either strategy as settled — the first night sampled them unevenly (7 against 9)
and the comparison is confounded by everything else that varies pull to pull.

### The enrage is not measured

The trade-off above references an enrage because the raid plays around one, but
**this builder does not know where it is and must not pretend to**. On the first
night only two pulls passed eight minutes, the longest ran to 8:48 with no damage
escalation in the per-10s profile, and the single `Grim Execution` in the log
landed at 8:12 in a pull that another pull had already survived past. If a later
night wipes to a clear enrage, measure it from that log and add it here; until
then the prose states the trade-off without a number.

Each burn row carries `transition`, `transition_mmss`, `band` and `p2_seconds`,
and the handover chart plots every pull's handover time against how much boss was
left, so the trade-off is visible rather than asserted.

## Gloombomb and the souls

`souls()` covers the chain the raid actually plays: Malacrass bombs exactly three
players, the blast damages them and anyone nearby, and **everyone it damages is
left Gravebound at three stacks** — as is whoever is in the frontal, which is why
the tanks lead the bound list while never being selected for the bomb.

Each Gravebound stack is a soul to collect, and every collection costs health.
That makes the damage two populations with a visible gap between them:

- **soul pickups** land around a tenth of a health bar (965 of them on the first
  night, median 10%);
- **the punishment for leaving one** lands around three quarters (22 of them,
  median 75%).

`FAILURE_HIT_SHARE` (40%) sits in the gap, and the split is what separates the
two ways the mechanic kills: collecting while already low, versus not collecting
at all. On the first night that was 9 against 19 of the 28 deaths it owns. Check
the histogram before moving that constant — if a future night fills the gap in,
the two-mode story stops being true and the page should stop telling it.

Gloombomb selection is not uniform: the ranged players were picked far more than
the melee (27 down to 2), which is worth watching across nights before treating
it as a targeting rule rather than a small-sample artefact.

## Defensives and consumables

`mitigation()` counts major cooldowns, minor/rotational mitigation, externals
given, healthstones and potions per raider, and flags the majors that landed
inside a **pressure window** — which on this boss is each shield channel plus
each intermission, rather than the geometrically-derived heavy spans the Ula'tek
builder uses.

Two things to know:

- Health at use subtracts the effective heal from the cast event's `hitPoints`,
  because WCL reports both as the value *after* the heal lands. That needs
  `player_casts` fetched with resources — it is, under a separate cache key.
- The spell tiers (`MAJOR`, `MINOR`, `EXTERNAL`, stones, potions) are imported
  from the Ula'tek builder rather than duplicated, since they are class-generic.
  A spec whose defensive is missing from those sets reads as **zero**, not as
  missing data. Adding Desperate Prayer for this report moved a holy priest from
  0 majors to 7; if a count looks wrong, check the list before concluding
  anything about the player. Editing those sets changes both reports.
- The reverse problem is `NOT_DEFENSIVE_FOR_SPEC`: a button that mitigates for
  one specialisation and is pure throughput for another. Metamorphosis inflated a
  havoc demon hunter by 58 casts — a third of their total — before it was
  excluded. Add to that map rather than removing the spell from `MAJOR`, which
  would break the spec it is a real defensive for.
- Tanks are excluded from this section entirely (`MITIGATION_SKIP_ROLES`). They
  press mitigation on cooldown as rotation, so including them answers "who is a
  tank" rather than "who pressed a save when the fight asked".
- **Raid-wide cooldowns are not externals.** The shared `EXTERNAL` set mixes
  cooldowns handed to one named player with ones dropped on the whole raid, and
  counting the second kind as "externals given" credits people with something
  they did not do for anybody in particular — on the first night that was three
  of the four healers, one of whom (Spirit Link Totem ×34) had given zero real
  externals. `RAID_WIDE` splits them out locally, so the other report's numbers
  do not move. It is checked **before** `MAJOR`, because a few raid cooldowns sit
  in that set too (Rallying Cry) and a raid cooldown is not a personal save
  whichever list it appears on.
- An external cast on **yourself** is a personal cooldown and bills as a major.
  A third of the mistweaver's Life Cocoons were self-cast.

## Editing the page

`template.html` is the page itself — HTML, CSS and the chart code. Two rules:

- Data goes in through `__PAYLOAD_<NAME>__` (one per `<script type="application/json">`).
- Any number in the prose goes in as `{{token}}`, computed in `render.tokens()`.
  Rendering fails loudly on a token the builder doesn't compute, so a new
  sentence can't silently keep last night's figure.

`spells.py` holds the names the analysis keys off — the orb debuffs, the frontal,
the shield and its channel, the two mind controls, the intermission buffs. Names
rather than ids, because Blizzard re-issues ids between patches; the report's own
ability table resolves whatever names are in that log.

The styling is lifted from the Ula'tek template so the reports read as one
family. If you restyle one, consider both.

## Known limits

- Boss-specific: it assumes this encounter's shape — carried orbs detonated by a
  frontal, a breakable absorb on a timer, an intermission burn window. Another
  boss needs another template.
- Phase data comes from Warcraft Logs' own phase transitions. If a future patch
  renumbers them, fix `spells.PHASES` rather than the analysis.
- `fetch.phases()` round-trips through JSON, which turns fight ids into strings;
  `Analysis.__init__` converts them back. Keep that conversion — without it every
  phase lookup silently returns empty on the second run, and the page builds
  wrong rather than failing.
