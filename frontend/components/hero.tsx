"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { StatChip } from "@/components/stat-chip";
import { useCorpusStats } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

export function Hero() {
  const { data, isLoading } = useCorpusStats();
  return (
    <section className="relative overflow-hidden rounded-2xl border bg-card px-8 py-10 sm:px-12 sm:py-12 shadow-[0_2px_4px_rgb(15_23_42_/_0.04),0_6px_18px_rgb(15_23_42_/_0.06)]">
      {/* soft brand glow in the corner */}
      <div
        aria-hidden
        className="pointer-events-none absolute -right-32 -top-32 h-[360px] w-[360px] rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--brand), transparent 86%) 0%, transparent 70%)",
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="relative"
      >
        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[var(--brand-soft)] bg-[var(--brand-tint)] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--brand)]">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inset-0 animate-ping rounded-full bg-[var(--brand)] opacity-60" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[var(--brand)]" />
          </span>
          Prep50 · Coverage
        </div>

        <h1 className="max-w-3xl text-4xl font-bold leading-[1.05] tracking-tight sm:text-[44px]">
          See how much of any exam paper
          <br className="hidden sm:inline" />{" "}
          already lives in the{" "}
          <span
            className="bg-clip-text text-transparent"
            style={{
              backgroundImage: "linear-gradient(135deg, var(--brand) 0%, #7c3aed 100%)",
            }}
          >
            Prep50 archive
          </span>
          .
        </h1>

        <p className="mt-3 max-w-2xl text-[16px] leading-relaxed text-muted-foreground">
          Drop in a new exam paper and we&apos;ll match every question against
          the full Prep50 archive in seconds, so you know exactly what already
          exists, what&apos;s a close variation, and what&apos;s truly new.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Link
            href="/check"
            className={buttonVariants({ size: "lg", className: "rounded-full px-5" })}
          >
            Start a new check
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
          <Link
            href="/batches"
            className={buttonVariants({ variant: "outline", size: "lg", className: "rounded-full px-5" })}
          >
            View history
          </Link>
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          <StatChip
            label="Questions in archive"
            value={isLoading ? "—" : fmtNumber(data?.total ?? 0)}
          />
          <StatChip
            label="WAEC subjects"
            value={isLoading ? "—" : Object.keys(data?.by_subject ?? {}).length}
          />
          <StatChip
            label="Average match time"
            value="< 5"
            unit="sec"
          />
        </div>
      </motion.div>
    </section>
  );
}
