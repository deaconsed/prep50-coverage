"use client";

import { useMemo } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";
import { VERDICT_ORDER, verdictLabel } from "@/lib/verdict";
import type { Verdict } from "@/lib/types";

interface Props {
  counts: Record<Verdict, number>;
  height?: number;
}

const COLORS: Record<Verdict, string> = {
  REPEAT: "var(--verdict-repeat)",
  NEAR_HIGH: "var(--verdict-near-high)",
  NEAR: "var(--verdict-near)",
  NEW: "var(--verdict-new)",
};

/** Standalone verdict-distribution donut. Shared between live and saved views. */
export function VerdictDonut({ counts, height = 200 }: Props) {
  const [tech] = useTechnicalMode();
  const data = useMemo(
    () =>
      VERDICT_ORDER.filter((v) => counts[v] > 0).map((v) => ({
        name: verdictLabel(v, tech),
        value: counts[v],
        verdict: v,
      })),
    [counts, tech],
  );

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-[12px] text-muted-foreground"
        style={{ height }}
      >
        Waiting for first result…
      </div>
    );
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Tooltip
            cursor={false}
            contentStyle={{
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              fontSize: 12,
            }}
          />
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius={Math.round(height * 0.28)}
            outerRadius={Math.round(height * 0.45)}
            paddingAngle={1.5}
            stroke="var(--card)"
            strokeWidth={2}
          >
            {data.map((d) => (
              <Cell key={d.verdict} fill={COLORS[d.verdict]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
