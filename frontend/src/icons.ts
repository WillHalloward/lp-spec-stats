/** Maps our short class name -> wowhead icon filename (no extension). */
const CLASS_ICON_NAME: Record<string, string> = {
  DK: "deathknight",
  DH: "demonhunter",
  Druid: "druid",
  Evoker: "evoker",
  Hunter: "hunter",
  Mage: "mage",
  Monk: "monk",
  Paladin: "paladin",
  Priest: "priest",
  Rogue: "rogue",
  Shaman: "shaman",
  Warlock: "warlock",
  Warrior: "warrior",
};

export function classIconUrl(cls: string): string | null {
  const name = CLASS_ICON_NAME[cls];
  return name ? `/icons/class/${name}.jpg` : null;
}

/** Inline <img> HTML for a class icon. Size in px. */
export function classIconImg(cls: string, size = 18): string {
  const url = classIconUrl(cls);
  if (!url) return "";
  return `<img class="class-icon" src="${url}" alt="${cls}" width="${size}" height="${size}">`;
}


// Spec icons: built from raid-helper's spec_emote Discord emoji IDs.
// Discord serves emoji images publicly at https://cdn.discordapp.com/emojis/<id>.png
import type { RawEvent } from "./types";

const specEmoteMap = new Map<string, string>();  // "Class::Spec(no digits)" -> emote_id

function specKey(cls: string, spec: string): string {
  return `${cls}::${spec.replace(/\d+$/, "")}`;
}

/** Populate the (class, spec) -> emoji-id map from raw event data. Call once at boot. */
export function indexSpecIcons(events: RawEvent[]): void {
  specEmoteMap.clear();
  for (const e of events) {
    for (const s of e.signups ?? []) {
      const eid = (s as { spec_emote?: string }).spec_emote;
      if (!eid || !s.class || !s.spec) continue;
      specEmoteMap.set(specKey(s.class, s.spec), eid);
    }
  }
}

export function specIconUrl(cls: string, spec: string): string | null {
  const id = specEmoteMap.get(specKey(cls, spec));
  return id ? `https://cdn.discordapp.com/emojis/${id}.png?size=64` : null;
}
