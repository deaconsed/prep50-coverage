"use client";

import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DeleteBatchButton } from "@/components/delete-batch-button";
import { VerdictPill } from "@/components/verdict-pill";
import { useBatches } from "@/lib/api";
import { fmtNumber, fmtRelativeTime, shortenSubject } from "@/lib/format";

/** Minimal batch history list — the fuller filterable view lands in Phase 5. */
export default function BatchesPage() {
  const { data, isLoading } = useBatches(100);
  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-10 space-y-6">
      <header>
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          Batches
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">History</h1>
        <p className="mt-1 text-[14.5px] text-muted-foreground">
          Every coverage check we&apos;ve run, newest first. Click any row to
          open the full report.
        </p>
      </header>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            {isLoading ? <Skeleton className="h-5 w-32" /> : `${fmtNumber(data?.length ?? 0)} run${(data?.length ?? 0) === 1 ? "" : "s"}`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !data?.length ? (
            <div className="rounded-lg border border-dashed py-16 text-center text-[13.5px] text-muted-foreground">
              No batches yet.
            </div>
          ) : (
            <ul className="divide-y divide-border/70">
              {data.map((b) => (
                <li
                  key={b.batch_id}
                  className="flex items-center gap-1 py-1 px-2 -mx-2 rounded-lg hover:bg-muted/60 transition-colors group"
                >
                  <Link
                    href={`/batches/${b.batch_id}`}
                    className="flex flex-1 items-center gap-4 py-2 min-w-0"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2.5">
                        <span className="font-semibold text-[14.5px]">
                          {b.subject_name ? shortenSubject(b.subject_name, 40) : "Mixed"}
                        </span>
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground tabular">
                          {fmtNumber(b.total)} q
                        </span>
                      </div>
                      <div className="mt-0.5 text-[12px] text-muted-foreground tabular truncate">
                        {b.batch_id} · {fmtRelativeTime(b.ingested_at)}
                      </div>
                    </div>
                    <div className="hidden sm:flex items-center gap-1.5">
                      {(["REPEAT", "NEAR_HIGH", "NEAR", "NEW"] as const).map((v) =>
                        b.counts[v] > 0 ? (
                          <span key={v} className="inline-flex items-center gap-1">
                            <VerdictPill verdict={v} size="sm" forceTechnical />
                            <span className="text-[11px] tabular text-muted-foreground">
                              {b.counts[v]}
                            </span>
                          </span>
                        ) : null,
                      )}
                    </div>
                  </Link>
                  <DeleteBatchButton
                    batchId={b.batch_id}
                    subjectName={b.subject_name}
                    total={b.total}
                  />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
