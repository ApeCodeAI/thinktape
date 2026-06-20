/**
 * Warm Editorial theme — ported from the web app's index.css.
 * Cream canvas, terracotta accent, serif accents on metadata.
 */
export const colors = {
  bg: "#fbf6ee",
  surface: "#fffdf8",
  surfaceWarm: "#f1e3cf",
  fg: "#201914",
  fg2: "#4c4037",
  muted: "#7a6d63",
  meta: "#9b5b32",
  border: "#ded2c3",
  borderSoft: "#eee4d7",
  accent: "#9b5b32",
  accentSoft: "#f4e3d2",
  accentOn: "#ffffff",
  danger: "#b33a3a",
  codeBg: "#f1e8da",
};

export const radius = { sm: 10, md: 16, lg: 24, pill: 999 };

export const space = (n: number) => n * 4;

export const typeMeta: Record<string, { label: string; mark: string }> = {
  thought: { label: "想法", mark: "✦" },
  bookmark: { label: "收藏", mark: "❖" },
  note: { label: "笔记", mark: "§" },
};

export const shadowRaised = {
  shadowColor: "#201914",
  shadowOpacity: 0.1,
  shadowRadius: 24,
  shadowOffset: { width: 0, height: 12 },
  elevation: 3,
};
