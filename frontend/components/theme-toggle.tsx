"use client";

import { Laptop, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

type Choice = "system" | "light" | "dark";
const CYCLE: Choice[] = ["system", "light", "dark"];
const META: Record<Choice, { label: string; Icon: typeof Sun }> = {
  system: { label: "Theme · system", Icon: Laptop },
  light: { label: "Theme · light", Icon: Sun },
  dark: { label: "Theme · dark", Icon: Moon },
};

/**
 * Compact theme toggle that cycles system → light → dark on click.
 * Mounted alongside the technical-detail toggle in the footer.
 *
 * Renders a stable placeholder during SSR (no theme is resolved on the
 * server) and swaps to the real state after mount — keeps the icon from
 * causing a hydration mismatch the way TechDetailToggle used to.
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const current: Choice = mounted
    ? CYCLE.includes(theme as Choice)
      ? (theme as Choice)
      : "system"
    : "system";
  const { label, Icon } = META[current];

  function cycle() {
    const i = CYCLE.indexOf(current);
    setTheme(CYCLE[(i + 1) % CYCLE.length]);
  }

  return (
    <button
      type="button"
      onClick={cycle}
      title={mounted ? label : "Theme"}
      className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-semibold text-muted-foreground hover:text-foreground bg-card border-border transition-colors"
    >
      <Icon className="h-3 w-3" />
      {mounted ? current.charAt(0).toUpperCase() + current.slice(1) : "System"}
    </button>
  );
}
