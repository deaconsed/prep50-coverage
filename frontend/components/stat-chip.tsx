import type { ReactNode } from "react";

interface Props {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
}

/**
 * Small bordered stat tile used in the hero and across stat strips.
 * Number is rendered with tabular numerals so a row of chips lines up neatly.
 */
export function StatChip({ label, value, unit, hint }: Props) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border bg-card px-4 py-3 shadow-[0_1px_2px_rgb(15_23_42_/_0.04)] min-w-[150px]">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </div>
      <div className="text-[22px] font-semibold leading-none tracking-tight tabular">
        {value}
        {unit && (
          <span className="ml-1 text-sm font-medium text-muted-foreground">
            {unit}
          </span>
        )}
      </div>
      {hint && <div className="text-[12px] text-muted-foreground">{hint}</div>}
    </div>
  );
}
