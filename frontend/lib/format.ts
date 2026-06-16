/** Number + date formatting helpers shared across the UI. */

export function fmtNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function fmtCosine(c: number): string {
  return c.toFixed(3);
}

/** Compact relative-time formatter for batch history rows. */
export function fmtRelativeTime(isoDate: string): string {
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** Map cosine score → short qualitative label (used in simple mode). */
export function cosineQualitative(cos: number): string {
  if (cos >= 0.9) return "Very strong match";
  if (cos >= 0.85) return "Strong match";
  if (cos >= 0.8) return "Moderate match";
  if (cos >= 0.75) return "Weak match";
  return "Distant match";
}

/** Year + Q-number label, e.g. "(2023, Q12)" or "(2023)". */
export function yearQLabel(
  year: number | null | undefined,
  qNum: number | null | undefined,
): string {
  if (year && qNum) return `(${year}, Q${qNum})`;
  if (year) return `(${year})`;
  if (qNum) return `(Q${qNum})`;
  return "";
}

/** Compact subject-name truncation for narrow chips/columns. */
export function shortenSubject(name: string, max = 22): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}
