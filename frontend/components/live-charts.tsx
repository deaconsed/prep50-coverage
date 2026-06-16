"use client";

import { motion } from "framer-motion";
import { useMemo } from "react";
import { Area, AreaChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { useTechnicalMode } from "@/lib/hooks/use-technical-mode";
import { Progress } from "@/components/ui/progress";
import { VERDICT_META, VERDICT_ORDER, verdictLabel } from "@/lib/verdict";
import type { Verdict } from "@/lib/types";

interface Props {
  counts: Record<Verdict, number>;
  done: number;
  total: number;
  phase: "idle" | "started" | "embedding" | "scoring" | "done" | "error";
  throughput: { t: number; n: number }[];
}

const PIE_COLORS: Record<Verdict, string> = {
  REPEAT: "var(--verdict-repeat)",
  NEAR_HIGH: "var(--verdict-near-high)",
  NEAR: "var(--verdict-near)",
  NEW: "var(--verdict-new)",
};

export function LiveCharts({ counts, done, total, phase, throughput }: Props) {
  const [tech] = useTechnicalMode();
  const pct = total > 0 ? (done / total) * 100 : 0;

  const pieData = useMemo(() => {
    return VERDICT_ORDER.filter((v) => counts[v] > 0).map((v) => ({
      name: verdictLabel(v, tech),
      value: counts[v],
      verdict: v,
    }));
  }, [counts, tech]);

  const tputData = useMemo(() => {
    if (throughput.length === 0) return [];
    // Normalize: relative seconds since the first sample.
    const t0 = throughput[0].t;
    return throughput.map((p) => ({ t: p.t - t0, n: p.n }));
  }, [throughput]);

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {/* Progress + verdict tally */}
      <div className="md:col-span-2 rounded-2xl border bg-card p-5 shadow-sm">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Live tally
            </div>
            <div className="mt-1 text-[15px] font-semibold">
              {done} of {total} {phase === "done" ? "checked" : "processed"}
            </div>
          </div>
          <PhaseBadge phase={phase} />
        </div>
        <Progress value={pct} className="mt-4 h-2 rounded-full" />
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {VERDICT_ORDER.map((v) => (
            <CountTile key={v} verdict={v} count={counts[v]} />
          ))}
        </div>
      </div>

      {/* Donut */}
      <div className="rounded-2xl border bg-card p-5 shadow-sm">
        <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Distribution
        </div>
        <div className="mt-2 h-[180px]">
          {pieData.length === 0 ? (
            <div className="flex h-full items-center justify-center text-[12px] text-muted-foreground">
              Waiting for first result…
            </div>
          ) : (
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
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={1.5}
                  stroke="var(--card)"
                  strokeWidth={2}
                >
                  {pieData.map((d) => (
                    <Cell key={d.verdict} fill={PIE_COLORS[d.verdict]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Throughput */}
      {tech && (
        <div className="md:col-span-3 rounded-2xl border bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Throughput · questions / sec
            </div>
            <div className="text-[12px] text-muted-foreground tabular">
              last {tputData.length} sec
            </div>
          </div>
          <div className="mt-2 h-[80px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={tputData} margin={{ top: 5, right: 0, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="tputFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--brand)" stopOpacity={0.55} />
                    <stop offset="100%" stopColor="var(--brand)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="n"
                  stroke="var(--brand)"
                  strokeWidth={2}
                  fill="url(#tputFill)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

function CountTile({ verdict, count }: { verdict: Verdict; count: number }) {
  const [tech] = useTechnicalMode();
  const m = VERDICT_META[verdict];
  return (
    <motion.div
      layout
      className="rounded-xl border bg-card/60 px-3 py-2.5 shadow-[inset_0_0_0_1px_var(--border)]"
    >
      <div className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: `var(--${m.cssVar})` }}
        />
        {tech ? m.technicalLabel : m.simpleLabel}
      </div>
      <motion.div
        key={count}
        initial={{ y: -4, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.18 }}
        className="mt-0.5 text-[22px] font-semibold tabular leading-none"
      >
        {count}
      </motion.div>
    </motion.div>
  );
}

function PhaseBadge({ phase }: { phase: Props["phase"] }) {
  const label = {
    idle: "Idle",
    started: "Starting",
    embedding: "Embedding",
    scoring: "Scoring",
    done: "Complete",
    error: "Error",
  }[phase];
  const tone =
    phase === "done"
      ? "bg-[var(--verdict-new-bg)] text-[var(--verdict-new-fg)]"
      : phase === "error"
      ? "bg-[var(--verdict-repeat-bg)] text-[var(--verdict-repeat-fg)]"
      : "bg-[var(--brand-tint)] text-[var(--brand)]";
  return (
    <span className={["rounded-full px-2.5 py-0.5 text-[11px] font-semibold", tone].join(" ")}>
      {label}
    </span>
  );
}
