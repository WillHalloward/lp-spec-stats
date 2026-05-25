/** Raw raid-helper event payload (subset of fields we use). */
export interface RawEvent {
  raidid: string | number;
  unixtime: number;
  leaderid: string;
  leadername: string;
  title?: string;
  displayTitle?: string;
  signups: RawSignup[];
  /** WCL encounter IDs we observed in this raid, attached server-side from
   *  the matched wcl_reports row. Used to derive raid-series filtering. */
  _encounter_ids?: number[];
  /** Admin overrides from event_overrides table, stamped server-side. */
  _override_difficulty?: string;
  _override_series_suffix?: string;
}

export interface RawSignup {
  userid: string;
  name: string;
  class: string;
  spec: string;
  role: string;
  status?: string;
  signuptime?: number;
}

/** Normalized event used by all charts. */
export interface Event {
  raidId: string;
  title: string;
  unixtime: number;
  leaderId: string;
  leaderName: string;
  category: "Raid" | "M+" | "Achievement" | "Mount";
  difficulty: "Mythic" | "Heroic" | "Normal" | "LFR" | "Other";
  raidName: string;
  seriesKey: string;
  seriesLabel: string;
  signups: RawSignup[];
  season: string;
  patch: string;
  /** Raid-series ids (Voidspire/Dreamrift/MQD) this event touched. Empty if
   *  unknown — events without WCL data and no recognizable raid keyword. */
  raids: string[];
}

export type Role = "Tank" | "Healer" | "Melee DPS" | "Ranged DPS";

export interface SignupClassification {
  kind: "attending" | "absence" | "generic";
  role?: Role;
}
