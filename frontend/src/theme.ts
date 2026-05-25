export const THEME = {
  bg: "#070912",
  surface: "#0f1424",
  surface2: "#181f33",
  border: "#262e44",
  borderSoft: "#1c2438",
  text: "#e6ebf5",
  textMuted: "#8b95ad",
  gold: "#e0a526",
  goldSoft: "#c08c1c",
  blue: "#3b82f6",
  blueSoft: "#2f6acc",
} as const;

export const CLASS_COLORS: Record<string, string> = {
  DK: "#C41E3A",
  DH: "#A330C9",
  Druid: "#FF7C0A",
  Evoker: "#33937F",
  Hunter: "#AAD372",
  Mage: "#3FC7EB",
  Monk: "#00FF98",
  Paladin: "#F48CBA",
  Priest: "#FFFFFF",
  Rogue: "#FFF468",
  Shaman: "#0070DD",
  Warlock: "#8788EE",
  Warrior: "#C69B6D",
};

export const DIFFICULTY_COLORS: Record<string, string> = {
  Normal: "#4a6fa5",
  Heroic: "#9b6dd6",
  Mythic: THEME.gold,
  LFR: "#5b6478",
  Other: "#737d95",
  "M+": "#10b981",
  Achievement: "#f0d068",
  Mount: "#ec4899",
};

export const ROLE_COLORS: Record<string, string> = {
  Tank: "#3b82f6",
  Healer: "#10b981",
  "Melee DPS": "#ef4444",
  "Ranged DPS": "#a855f7",
};
