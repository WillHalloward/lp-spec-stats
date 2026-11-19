# The Coiled Altar — Mythic research notes

Groundwork for a Mythic prog-night page. The heroic builder (`README.md`) still
describes heroic; **do not reuse its constants on Mythic without re-measuring**.

First log: `3aw7TmPX2t6Zfr4g`, Piian's Mid-Pressure, 19 Nov 2026. 35 Mythic pulls,
no kill. Best pull: #35, reached Stage Three, ended 22.5% (`fightPercentage`).

Tags: **[log]** = measured in that log; **[guide]** = from a guide only, not yet
checked. Guides: Method Mythic (updated 3 Oct 2026), MythicTrap Mythic,
wowutils/Viserio, Wowhead (Retaliatory Malice). **Every guide we read was written
before the 13 Oct and 5 Nov nerfs**, so check its numbers against the hotfix
timeline below. Where they disagree, the hotfixes and the log win.

## Shape of the fight [log]

| Stage | Who | Start (pull 35) | How it ends |
|---|---|---|---|
| P1 Serpent's Bargain | Zul'jan | 0:00 | push, 145–167s across pulls |
| P2 Usurper's Reprisal | Malacrass (Zul'jan still up) | ~2:30 | damage push on Malacrass |
| INT The Claimed Vessel | Soulbinding, Zul'jan resurrects | 5:40 | channel ends |
| P3 Coiled Union | both, kill together (Soulbound) | 6:18 | kill |

P1 is a fixed script. Pull 35's casts are the same in every pull to the tenth of
a second:

```
0.0  Fangs    2.0 Deluge   23 Sever  30 Venomfang  40 Sever  43.0 Guillotine mark (lands 48.0)
45 Deluge     60 Sever     65 Venomfang  77 Sever   85 Fangs  87 Deluge
108 Sever     115 Venomfang  125 Sever  128.0 Guillotine mark (lands 133.0)  130 Deluge  145 Sever → push
```

P2, per cycle (~35–48s): Dreadmarch → Spiritcackle (+5s) → Gloombomb (+7s) →
Soul Sever (+18s). Eternal Nightfall at ~224–246s and ~309–322s.

Night totals: 18 pulls ended in P1, 16 in P2, 1 reached INT and P3.

## Mechanics

### Stage One — Zul'jan

- **Coalesced Venom** (orbs). Walking over one picks it up (**Volatile Venom**,
  5s debuff [guide]), and while you carry it you take ticking damage. The orbs
  get dropped into the tank frontal. [log: 11–20 green pickups per full P1]
- **Sever** (tank frontal, every ~17–20s) detonates every orb in it. Each orb
  detonated puts **one stack of Venom Rupture on the whole raid**. [log: +2 to +7
  stacks per Sever. The debuff falls off between Severs, so each Sever starts at 0]
- **Virulent Mutation** (Mythic, the purple orb). Some of the orbs from each
  Toxic Deluge come out purple. Picking one up gives you **Mutagenic Venom**: you
  carry it, it hits everyone within 8 yd (6 yd after the hotfix) for 5s, then it
  drops again. If it touches any other orb it explodes and applies **20 stacks of
  Venom Rupture**, which wipes the raid. Any left on the ground when the next
  Deluge is cast also explode. **4 per Deluge since 13 Oct** (Method's "5" is
  outdated), and the radius is **6 yd** (was 8). [Not counted in the log yet: the
  Virulent Mutation NPC has no events in the streams we fetch. log: 8–17 purple
  pickups per pull]
- **Toxic Deluge** spawns the next batch of orbs (2s, 45s, 87s, 130s). The
  first P1 Deluge makes 8 orbs (10 before 13 Oct).
- **Fangs of the Coiled Altar** (0s, 85s): raid-wide pulsing damage that leaves
  growing poison puddles (**Noxious Ground**) and gives Zul'jan **Twinfang
  Toxin** stacks on his melee.
- **Guillotine**: **one per window**. The cast at 43.0 marks a player, a
  second cast event at 46.5 is the same axe coming down, and it lands at 48.0;
  likewise 128.0 → 133.0. Everyone hit at the landing shares it (the marked
  player included). A soak needs at least 5 players. If it doesn't get them, it
  becomes **Execution**, ~1.58M Nature damage to everyone. [log: soakers per
  window are usually 7–10. Every Execution came on a window with 0–1 soakers]
  Soakers get a long vulnerability debuff, so the two windows use different
  groups. Method's plan: window 1 is 6 players (melee and hunters, plus Zephyr),
  window 2 is 2 tanks + 3 immunities + a BoP'd target.
- **Axegrinder**: spinning axes to dodge. On Heroic and Mythic they don't despawn.
- **Venomfang**: a dispellable poison DoT on random players (30s, 65s, 115s).
- **Widow's Touch / Widow's Kiss** (54s): one hit on the raid, and a ~1.19M hit
  on one target. [log, purpose not researched]
- **The push**: every orb still alive when P1 ends detonates. [log: +7 to +10
  Rupture stacks in one burst at 145–162s. Method expects 10–11 and plans
  Darkness, Spirit Link Totem and AMZ for it]

### Stage Two — Hex Lord Malacrass

- **Dreadful Presence**: a raid aura that ticks all phase. It's the biggest
  damage source in P2 (247M on pull 35).
- **Dreadmarch**: mind controls players and walks them to the edge until their
  absorb is broken. **3 targets per cast** since 13 Oct (was 4). [log: exactly 3
  per cast, every cast. Extra single applications between casts are ghost
  catches. Absorb **568,393** (heroic 494,352), 5 casts per full P2. A burst of
  15 at once (pull 33, 381s) is the end-of-P2 mass mind control from a failed
  push]. Victims should cancel their own shields and
  absorbs. Have a stun or grip ready for every cast.
- **Manifestation of Dread** (ghosts, **Unnerving Fixation**): on Mythic only the
  fixated player can see their ghost. A ghost touching its player mind controls
  them. Two ghosts touching put **Malevolent Resonance** on both fixated players
  (shadow damage for 5s; **−60% on 5 Nov**, so it is survivable now). [log: 84
  Resonance applications over 17 P2 pulls]. Since 13 Oct a ghost despawns when
  its player dies instead of picking someone new, and the frontal's
  detection/stun angle is 10° wider.
- **Soul Sever** (tank frontal): kills every ghost it hits. Leaves the tank with
  **Gravebound** and a vulnerability debuff.
- **Spiritcackle** summons **one Spiteful Soulcoiler** (**2 before 5 Nov**, so
  Method's two-add plan, with melee taking one and ranged the other, is
  outdated). [log: one instance per cast, Spirit Shield goes up with 2 stacks,
  and each overlapping Gloombomb strips one. On the full P2s, the second strip
  came 7–12s after the shield went up]. Wail of Terror is a 10s cast on Mythic
  (raised 15 Sep). It spawns near Malacrass more often. It casts **Wail of Terror**, a raid fear that must be interrupted.
  At full energy it becomes **Unassailable** and can't be interrupted. It also
  casts **Retaliatory Malice**, 250,022 shadow damage to random players every 3s
  while it lives. On Mythic it spawns with **Spirit Shield** (99% damage
  reduction), and each overlapping Gloombomb strips one application.
  [log: 162 Wail begincasts against 120 completed `cast` events. Interrupts are
  not in the stream fetched yet, so that ratio isn't proven to be the kick rate]
- **Gloombomb**: 4 targets (2 melee, 2 ranged [guide]). [log: 158 targets over
  41 casts = 3.9]. The explosion splits your soul, and you have 10s to collect 3
  souls or you die. Since 5 Nov the explosion does 20% less damage and the soul
  fragments last 2s longer.
- **Eternal Nightfall / Veil of Twilight**: Malacrass gets a **34,828,260**
  absorb [log] and channels Nightfall, which kills the raid if it completes. It
  also stacks **Suffocating Darkness** heal absorbs. The cast got **+2s** on
  13 Oct, all difficulties, which fits the ~17s seen. Heroic's −15% Veil absorb
  (25 Aug) did not touch Mythic. [log: Veil drops ~17s after
  it goes up when the cast completes, and the deaths land that same second
  (pulls 6, 13, 15, 26, 29). Breaks came at 10.7–16.1s, and some only just made
  it (28: 16.1s, 33: 15.9s)]
- **The end of P2** [guide]: hold damage until the frontal clears the ghosts,
  then push to 0 within ~5s, or the raid is mind controlled and the boss resets.

### Intermission — The Claimed Vessel

- **Soulbinding**: Zul'jan resurrects, takes +100% damage, and Malacrass goes
  immune behind **Deathguard**. This is the lust window.
- **Fragments of Malacrass** walk at Zul'jan. Body-blocking one puts **Spirit
  Erasure** on the raid, which on Mythic also adds a stacking 20% vulnerability
  for 2s [guide]. 25% fewer fragments on Mythic since 15 Sep. A fragment that reaches Zul'jan heals him (**Reclaim
  Essence**): 10% on Mythic per Method, 3% on Heroic. [log: Spirit Erasure
  reached **12 stacks** on pull 35, where Method says ≤4 is always safe. No Reclaim
  Essence heal found in `enemy_heals`, so it still needs finding]

### Stage Three — Coiled Union

Everything from before, combined: orbs and Deluge, **Blighted Sever**, ghosts
and Dreadmarch, Soulcoilers, Gloombomb, Eternal Nightfall. On top of that:

- **Grim Guillotine** ×3. If it isn't soaked, it becomes **Grim Execution** on
  the raid. [log: pull 35 ended on one at 403s with 1 soaker]
- **Defilement of the Coiled Altar**: an 8s channel that puts big absorbs on the
  raid and on the ground. **Corrupted Toxin** stacks on the tanks, so they swap.
- **Death's Embrace**, **Dread Bolt** (on the tank).
- **Soulbound**: if one boss dies alone, the other enrages. Balance their health.

### Not identified

- **Unworthy** is **not** the Guillotine fail. It lands at ~10s, before any
  Guillotine has been cast (first mark at 43s), and it hits only some players
  (1–13). The failed soak is **Execution**.
- **Unworthy**: 41.67M unmitigated to each player it hits (1–13 of them) at ~10.0s. It fires only on the
  ≤30s reset pulls (8, 16, 20, 21, 27), after players had died with no killing
  ability, plus once at 157s on pull 23 after a collapse. It looks like a reset
  or out-of-bounds kill. Cause unknown, so keep these pulls out of the stats.

## Nerf / hotfix timeline (Mythic-relevant)

Compiled from secondary sites: GamGem's change log, plus AccountShark,
MasterOfWarcraft and 1vX write-ups of the official posts. Blizzard's own pages
weren't fetched, so treat the exact dates as ±a few days. ✔ = the 19 Nov log
agrees.

| Date | Change | Diff. |
|---|---|---|
| 19 Aug | Bosses no longer regain too much health in the intermission (fix) | all |
| 25 Aug | Malacrass P3 health −10%; Veil of Twilight absorb −15% | **N/H only** |
| 25 Aug | Dreadmarch hits the whole raid 10s after enrage (buff) | all |
| 27 Aug | Zul'jan at 1 HP at INT end no longer unkillable in P3 (fix) | all |
| 31 Aug | **Defilement of the Coiled Altar heal absorb −20%** | Mythic |
| 1 Sep | **Coalesced Venom dmg −15%, Venom Rupture dmg −10%** | Mythic |
| 1 Sep | Guillotine/Grim Guillotine need only 3 soakers | **LFR/N/H only**, so Mythic still needs 5 |
| 15 Sep | Venom Rupture −10% (H & M); Mutagenic Venom dmg −15% | H/M |
| 15 Sep | **Wail of Terror cast 10s** on Mythic; Soulcoiler spawn/move more predictable, spawns near Malacrass more often | Mythic |
| 15 Sep | Dreadmarch no longer grows in target count during the phase | all |
| 15 Sep | Ghosts avoid already-fixated players; ghosts revealed by a Wail kick stay visible 3s longer | all |
| 15 Sep | **Fragments of Malacrass −25%** in the intermission | Mythic |
| 13 Oct | **Toxic Deluge P1: 8 orbs (was 10); Virulent Mutations 4 (was 5)** | Mythic |
| 13 Oct | **Dreadmarch 3 targets (was 4)** ✔ | Mythic |
| 13 Oct | Virulent Mutation / Mutagenic Venom radius 6 yd (was 8) | unstated |
| 13 Oct | **Eternal Nightfall cast +2s** ✔ (Veil ends at ~17s) | all |
| 13 Oct | Ghosts glow red for their player from fixation start; despawn when their player dies; stun angle +10° | all |
| 5 Nov | **Spiritcackle: 1 Soulcoiler (was 2)** ✔ | Mythic |
| 5 Nov | Axegrinder dmg −20% (Mythic), move speed −20% (all) | M / all |
| 5 Nov | Gloombomb dmg −20%; Gravebound soul fragments last +2s | Mythic |
| 5 Nov | Venom Rupture dmg −15% | Mythic |
| 5 Nov | Malevolent Resonance dmg −60% | unlabelled |

Sources disagree on two points. GamGem lists Venom Rupture −10% on both 1 Sep
and 15 Sep, which may be one change logged twice. Whether the 6-yd radius
applies to Mythic is unconfirmed.

What this does to the guides:
- **Method (3 Oct)**: its Mutation count (5), Dreadmarch count (4) and two-add
  Soulcoiler plan (melee add / ranged add, kick sets on both, "both must die
  before the next Dreadmarch") are all outdated. Its 3+2 purple split per Sever
  pair assumed 5 Mutations; with 4 it's presumably 2+2 or 3+1, so check the
  raid's own plan.
- Any damage figure for Venom Rupture, Coalesced Venom, Axegrinder, Gloombomb or
  Resonance from before 5 Nov reads high. Use the log's numbers.
- Things the nerfs **didn't** change: purple explosion = 20 Rupture stacks (still
  a wipe); the Mythic Guillotine still needs 5; the Veil absorb on Mythic
  (34.8M, log).

## What ended the pulls — first pass [log]

Read off Venom Rupture bursts, Execution hits and Veil timing. Not yet
reconciled into one cause per pull.

| Cause | Pulls |
|---|---|
| Purple carried into another orb (touched) | 3, 10, 12, 14, 25, 30, 34 |
| Purple **left on the ground**, blew on the next Deluge (130s / 87s / P3 424s) | 2, 24 (also 22, 34, 35 after the wipe had started) |
| Guillotine → Execution | 9 (1 soaker, 16 alive: the cause). 2, 22, 24, 31 came after the wipe had started |
| Eternal Nightfall resolved (Veil not broken) | 6, 13, 15, 26 (2nd), 29 |
| Grim Guillotine → Grim Execution | 35 |
| ≤30s reset (Unworthy) | 8, 16, 20, 21, 27 |

So the purple orb is the main wall: about 11 of 35 pulls. Some explosions have
nobody carrying a purple and land exactly on a Toxic Deluge cast; those are
Mutations left on the ground, which is a separate fix from bumping into one.
(Corrected 19 Nov: pull 16's explosion was a reset pull, not counted.) Sever and Venom
Rupture also make up most of the early P1 deaths before a wipe. The all-death
totals are mostly wipe despawn and shouldn't be headlined.

## Stats that matter

The order follows where pulls die (P1 first). "Signal" is what the log carries.
✅ = measurable now, verified above. ⚠️ = should work, not built yet.
❓ = needs a new fetch or more research.

### P1 — orbs (the main wall)
1. ✅ **Rupture stacks per Sever.** Signal: Venom Rupture applydebuff(stack)
   bursts on each Sever. Shows how evenly the orbs are spread over the 7 Severs.
   Method wants ~3 purple orbs on Sever 1 and 2 on Sever 2, plus 3–4 greens each.
2. ✅ **Purple explosions.** Signal: a single burst of ≥15 Rupture stacks. Gives
   when it happened and which carrier: whoever had Mutagenic Venom, or dropped
   it, closest to the burst.
3. ⚠️ **Purple handling per player.** Signal: Mutagenic Venom pickups, hold
   time, and where it was dropped against the Sever that detonated it.
4. ⚠️ **Green carries per player.** Signal: Volatile Venom, and who carried the
   most (carry damage).
5. ❓ **Virulent Mutations left at Deluge.** Needs the Virulent Mutation actor's
   events (spawn/death), probably from a dedicated query with no hostility filter.
6. ✅ **Push stacks.** Signal: the Rupture burst at P1→P2, plus raid health and
   raid cooldowns (Darkness/SLT/AMZ) on it. Target is ~10.
7. ⚠️ **Deaths to Sever / Coalesced Venom / Mutagenic Venom.** People standing
   in the frontal or touching orbs, counted before the collapse.

### P1 — the rest
8. ✅ **Guillotine soakers per window**, and Executions. Also check who soaked
   against the plan, and whether the window-2 immunities were actually up.
9. ⚠️ **Axegrinder hits per player** (avoidable).
10. ⚠️ **Noxious Ground hits per player** (avoidable puddles).
11. ⚠️ **Venomfang dispel latency.**

### P2
12. ✅ **Veil break time** (apply → remove; ~17s = failed), plus damage per
    player into the Veil, and Font trinket / cooldown use.
13. ⚠️ **Dreadmarch**: targets, absorb broken (568,393, measured from the
    `absorbed` records as in the heroic builder), time to break, falls, and who
    stunned or gripped.
14. ⚠️ **Malevolent Resonance**: which pairs touched, and the deaths.
15. ❓ **Soulcoiler kicks** (one add per cast now): Wail begincasts against interrupts per kick set,
    whether it reached Unassailable, time alive, and Retaliatory Malice damage
    taken while it lived. Needs the interrupt events fetched.
16. ✅ **Spirit Shield**: time from shield up to both stacks stripped
    (log: 7–12s), and which Gloombomb pairs did it.
17. ⚠️ **Gloombomb**: souls collected in time, clipped bystanders, and deaths.
18. ⚠️ **Ghost catches.** Reuse `march_sources()` from the heroic builder (cast
    vs catch), and check that its grace windows hold on Mythic.
19. ⚠️ **End-of-P2 push timing** against when the ghosts were cleared.
20. ⚠️ **Dreadful Presence healing**: raid HP across P2 and when people died
    to it.

### Intermission / P3 (one pull so far — list, don't headline)
21. ✅ **Spirit Erasure max stacks per player** (≤4 is the plan; 12 seen).
22. ❓ **Fragments that reached Zul'jan.** Find where Reclaim Essence logs on
    Mythic.
23. ⚠️ **Zul'jan HP at the end of INT** (from the heroic builder's
    `serpent_hp_end`).
24. ✅ **Grim Guillotine soakers** / Grim Execution.
25. ⚠️ **Health of both bosses through P3** (Soulbound balance).

### Every phase
26. ⚠️ **What ended each pull**: one cause per pull from the first deaths
    before the collapse, reusing the heroic `edge()` reset/collapse rules, and
    dropping the Unworthy reset pulls.
27. ⚠️ **Progress per pull.** `fightPercentage` blends both bosses, so plot the
    phase reached plus time in phase instead, or per-boss HP from damage events.
28. ⚠️ **Defensives, healthstones and potions** (the heroic `mitigation()`), with
    pressure windows moved to the push, the Veils and the INT.

## Open questions before building

- Do Virulent Mutation actor events exist in another data type?
- Where do interrupts land in our fetch: `player_casts` type `interrupt` came
  back empty. Try `dataType: Interrupts`.
- What actually triggers Unworthy?
- Does each green orb still equal 1 Rupture stack on Mythic (the heroic
  identity)? The +2…+7 per Sever looks right for that, but it hasn't been checked
  against the orbs placed.
