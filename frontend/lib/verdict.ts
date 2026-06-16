/**
 * Verdict labeling + visual mapping.
 *
 * Two display modes:
 *   - technical: surfaces all detail (cosine scores, fingerprint badges,
 *     model/threshold strings) — engineers, calibrating, debugging.
 *   - simple: hides the numbers and shows reviewer-friendly language —
 *     subject-matter reviewers, demo audiences, exec views.
 *
 * Default mode comes from NEXT_PUBLIC_SHOW_TECHNICAL (env). Per-session
 * override via ?tech=1 in URL or localStorage["prep50:tech"] = "1".
 * The `useTechnicalMode` hook in `lib/hooks/use-technical-mode.ts` handles the
 * lookup; this file is just the label table.
 */
import type { Verdict } from "./types";

export interface VerdictMeta {
  /** internal verdict key */
  key: Verdict;
  /** label shown in technical mode */
  technicalLabel: string;
  /** label shown in simple mode (reviewer-friendly) */
  simpleLabel: string;
  /** one-line description for tooltips and explanations */
  description: string;
  /** CSS variable name for the accent color (without --) */
  cssVar: string;
  /** tone family — used by chart slice colors and stat-chip accents */
  tone: "danger" | "warning" | "caution" | "success";
}

export const VERDICT_META: Record<Verdict, VerdictMeta> = {
  REPEAT: {
    key: "REPEAT",
    technicalLabel: "REPEAT",
    simpleLabel: "Exact match",
    description: "Identical canonical template found in the historical corpus.",
    cssVar: "verdict-repeat",
    tone: "danger",
  },
  NEAR_HIGH: {
    key: "NEAR_HIGH",
    technicalLabel: "NEAR (high)",
    simpleLabel: "Very similar",
    description: "No template match, but strong semantic overlap — review recommended.",
    cssVar: "verdict-near-high",
    tone: "warning",
  },
  NEAR: {
    key: "NEAR",
    technicalLabel: "NEAR",
    simpleLabel: "Similar",
    description: "Moderate semantic overlap with at least one historical question.",
    cssVar: "verdict-near",
    tone: "caution",
  },
  NEW: {
    key: "NEW",
    technicalLabel: "NEW",
    simpleLabel: "New question",
    description: "No close match in the historical corpus.",
    cssVar: "verdict-new",
    tone: "success",
  },
};

export function verdictLabel(v: Verdict, technical: boolean): string {
  const m = VERDICT_META[v];
  return technical ? m.technicalLabel : m.simpleLabel;
}

/** Tailwind class fragments for verdict-themed pills and bars. */
export const VERDICT_CLASS = {
  REPEAT: {
    pill: "bg-[var(--verdict-repeat-bg)] text-[var(--verdict-repeat-fg)]",
    dot: "bg-[var(--verdict-repeat)]",
    bar: "bg-[var(--verdict-repeat)]",
  },
  NEAR_HIGH: {
    pill: "bg-[var(--verdict-near-high-bg)] text-[var(--verdict-near-high-fg)]",
    dot: "bg-[var(--verdict-near-high)]",
    bar: "bg-[var(--verdict-near-high)]",
  },
  NEAR: {
    pill: "bg-[var(--verdict-near-bg)] text-[var(--verdict-near-fg)]",
    dot: "bg-[var(--verdict-near)]",
    bar: "bg-[var(--verdict-near)]",
  },
  NEW: {
    pill: "bg-[var(--verdict-new-bg)] text-[var(--verdict-new-fg)]",
    dot: "bg-[var(--verdict-new)]",
    bar: "bg-[var(--verdict-new)]",
  },
} as const;

/** Reorder/rename when surfacing in simple mode to non-technical reviewers. */
export const VERDICT_ORDER: Verdict[] = ["REPEAT", "NEAR_HIGH", "NEAR", "NEW"];
