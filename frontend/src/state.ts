import type { RawSignup, Role } from "./types";
import { classifySignup, attendingSignups } from "./normalize";
import type { Event } from "./types";

/** Global, cross-chart filter state. */
export interface FilterState {
  classes: Set<string>;        // empty = all
  roles: Set<Role>;            // empty = all
  difficulties: Set<string>;   // empty = all
  seasons: Set<string>;        // empty = all
  patches: Set<string>;        // empty = all
  raids: Set<string>;          // empty = all; ids from RAIDS in normalize.ts
  raidSeries: Set<string>;     // empty = all; matches Event.seriesLabel
}

type Listener = (state: FilterState) => void;

class Store {
  // Default to the current season so the page opens with the same view as before.
  state: FilterState = {
    classes: new Set(),
    roles: new Set(),
    difficulties: new Set(),
    seasons: new Set(["midnight-s1"]),
    patches: new Set(),
    raids: new Set(),
    raidSeries: new Set(),
  };
  private listeners: Listener[] = [];

  subscribe(fn: Listener): () => void {
    this.listeners.push(fn);
    return () => { this.listeners = this.listeners.filter(l => l !== fn); };
  }

  private notify(): void {
    for (const l of this.listeners) l(this.state);
  }

  toggleClass(cls: string): void {
    if (this.state.classes.has(cls)) this.state.classes.delete(cls);
    else this.state.classes.add(cls);
    this.notify();
  }

  toggleRole(role: Role): void {
    if (this.state.roles.has(role)) this.state.roles.delete(role);
    else this.state.roles.add(role);
    this.notify();
  }

  toggleDifficulty(d: string): void {
    if (this.state.difficulties.has(d)) this.state.difficulties.delete(d);
    else this.state.difficulties.add(d);
    this.notify();
  }

  toggleSeason(s: string): void {
    if (this.state.seasons.has(s)) this.state.seasons.delete(s);
    else this.state.seasons.add(s);
    this.notify();
  }

  togglePatch(p: string): void {
    if (this.state.patches.has(p)) this.state.patches.delete(p);
    else this.state.patches.add(p);
    this.notify();
  }

  toggleRaid(r: string): void {
    if (this.state.raids.has(r)) this.state.raids.delete(r);
    else this.state.raids.add(r);
    this.notify();
  }

  toggleRaidSeries(s: string): void {
    if (this.state.raidSeries.has(s)) this.state.raidSeries.delete(s);
    else this.state.raidSeries.add(s);
    this.notify();
  }

  clearClasses(): void { this.state.classes.clear(); this.notify(); }
  clearRoles(): void { this.state.roles.clear(); this.notify(); }
  clearDifficulties(): void { this.state.difficulties.clear(); this.notify(); }
  clearSeasons(): void { this.state.seasons.clear(); this.notify(); }
  clearPatches(): void { this.state.patches.clear(); this.notify(); }
  clearRaids(): void { this.state.raids.clear(); this.notify(); }
  clearRaidSeries(): void { this.state.raidSeries.clear(); this.notify(); }
  clearAll(): void {
    this.state.classes.clear();
    this.state.roles.clear();
    this.state.difficulties.clear();
    this.state.seasons.clear();
    this.state.patches.clear();
    this.state.raids.clear();
    this.state.raidSeries.clear();
    this.notify();
  }

  hasAny(): boolean {
    return this.state.classes.size + this.state.roles.size + this.state.difficulties.size > 0;
  }
}

export const filterStore = new Store();


/** Apply current filter to a signup. Returns true if the signup should be counted. */
export function matchesFilter(s: RawSignup, eventDifficulty: string, state: FilterState): boolean {
  const c = classifySignup(s);
  if (c.kind !== "attending" || !c.role) return false;
  if (state.classes.size > 0 && !state.classes.has(s.class)) return false;
  if (state.roles.size > 0 && !state.roles.has(c.role)) return false;
  if (state.difficulties.size > 0 && !state.difficulties.has(eventDifficulty)) return false;
  return true;
}


/** Filtered iterator: yields only signups matching the active filter.
 * Role may be undefined for synthesized WCL signups; when the role filter is active,
 * those signups are excluded (no match for undefined).
 */
export function* filteredSignups(
  events: Event[],
  state: FilterState,
): Generator<[Event, RawSignup, Role | undefined]> {
  for (const [event, signup, role] of attendingSignups(events)) {
    if (state.seasons.size > 0 && !state.seasons.has(event.season)) continue;
    if (state.patches.size > 0 && !state.patches.has(event.patch)) continue;
    if (state.raids.size > 0 && !event.raids.some(r => state.raids.has(r))) continue;
    if (state.raidSeries.size > 0 && !state.raidSeries.has(event.seriesLabel)) continue;
    if (state.classes.size > 0 && !state.classes.has(signup.class)) continue;
    if (state.roles.size > 0 && (!role || !state.roles.has(role))) continue;
    if (state.difficulties.size > 0 && !state.difficulties.has(event.difficulty)) continue;
    yield [event, signup, role];
  }
}
