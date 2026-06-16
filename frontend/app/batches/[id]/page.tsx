"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { ArrowLeft, Download } from "lucide-react";

import { CoverageBanner } from "@/components/coverage-banner";
import { DeleteBatchButton } from "@/components/delete-batch-button";
import { SummaryTiles } from "@/components/summary-tiles";
import { VerdictCard } from "@/components/verdict-card";
import { VerdictDonut } from "@/components/verdict-donut";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { API_BASE, useBatch } from "@/lib/api";
import { fmtNumber, fmtRelativeTime } from "@/lib/format";
import type { Verdict, VerdictItem } from "@/lib/types";

export default function BatchDetailPage({ params }: { params: Promise<{ id: string }> }) {
  // Next.js 16: params is now a promise.
  const { id } = use(params);
  const { data, isLoading, error } = useBatch(id);
  const [filter, setFilter] = useState<Verdict | "ALL">("ALL");

  const filtered = useMemo<VerdictItem[]>(() => {
    if (!data) return [];
    if (filter === "ALL") return data.items;
    return data.items.filter((it) => it.verdict === filter);
  }, [data, filter]);

  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-6xl px-6 py-10 space-y-6">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto w-full max-w-6xl px-6 py-10">
        <Link
          href="/batches"
          className={buttonVariants({ variant: "ghost", size: "sm", className: "rounded-full" })}
        >
          <ArrowLeft className="mr-1.5 h-3.5 w-3.5" />
          Back to history
        </Link>
        <div className="mt-8 rounded-2xl border border-[var(--verdict-repeat-bg)] bg-[var(--verdict-repeat-bg)]/60 p-6 text-[14px] text-[var(--verdict-repeat-fg)]">
          Could not load this batch: {error instanceof Error ? error.message : "Not found."}
        </div>
      </div>
    );
  }

  const summary = data.summary;
  const subjectName = data.items[0]?.input.subject_name ?? "Mixed";
  const counts: Record<Verdict, number> = {
    REPEAT: summary.REPEAT ?? 0,
    NEAR_HIGH: summary.NEAR_HIGH ?? 0,
    NEAR: summary.NEAR ?? 0,
    NEW: summary.NEW ?? 0,
  };

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8 sm:py-10 space-y-6">
      <Link
        href="/batches"
        className={buttonVariants({
          variant: "ghost",
          size: "sm",
          className: "rounded-full text-[12.5px] -ml-2",
        })}
      >
        <ArrowLeft className="mr-1.5 h-3.5 w-3.5" />
        Back to history
      </Link>

      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Batch report
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">{subjectName}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground tabular">
            <span>{fmtNumber(summary.total)} questions</span>
            <span>·</span>
            <span>{fmtRelativeTime(data.meta.ingested_at)}</span>
            <span>·</span>
            <span className="font-mono text-[12px]">{data.meta.batch_id}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <a
            href={`${API_BASE}/api/batches/${data.meta.batch_id}`}
            target="_blank"
            rel="noreferrer"
            className={buttonVariants({
              variant: "outline",
              size: "sm",
              className: "rounded-full",
            })}
          >
            <Download className="mr-1.5 h-3.5 w-3.5" />
            Download JSON
          </a>
          <DeleteBatchButton
            batchId={data.meta.batch_id}
            subjectName={subjectName}
            total={summary.total}
            variant="labeled"
            redirectTo="/batches"
          />
        </div>
      </header>

      <CoverageBanner summary={summary} subjectName={subjectName} />

      <div className="grid gap-4 md:grid-cols-3">
        <div className="md:col-span-2 rounded-2xl border bg-card p-5 shadow-sm">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-3">
            Filter results
          </div>
          <SummaryTiles counts={counts} filter={filter} onFilter={setFilter} />
        </div>
        <div className="rounded-2xl border bg-card p-5 shadow-sm">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Distribution
          </div>
          <VerdictDonut counts={counts} height={180} />
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Results
          {filter !== "ALL" && (
            <span className="ml-2 normal-case tracking-normal text-[12.5px] text-muted-foreground">
              filtered · {fmtNumber(filtered.length)}
              <button
                type="button"
                onClick={() => setFilter("ALL")}
                className="ml-1 underline hover:no-underline"
              >
                clear
              </button>
            </span>
          )}
        </div>
      </div>

      <div className="space-y-3">
        {filtered.map((it, i) => (
          <VerdictCard
            key={i}
            item={it}
            index={it.input_index}
            total={summary.total}
            animate={false}
            items={filtered}
            position={i}
          />
        ))}
        {filtered.length === 0 && (
          <div className="rounded-2xl border border-dashed py-16 text-center text-[13.5px] text-muted-foreground">
            No items in this filter.
          </div>
        )}
      </div>
    </div>
  );
}
