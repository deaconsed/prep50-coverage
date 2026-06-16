"use client";

import Link from "next/link";

import { Hero } from "@/components/hero";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useBatches } from "@/lib/api";
import { fmtNumber, fmtRelativeTime, shortenSubject } from "@/lib/format";
import { VerdictPill } from "@/components/verdict-pill";

export default function Home() {
  const { data: batches, isLoading } = useBatches(5);
  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8 sm:py-10 space-y-10">
      <Hero />

      <section className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle className="text-base">How it works</CardTitle>
          </CardHeader>
          <CardContent className="text-[14px] leading-relaxed text-muted-foreground space-y-3">
            <div>
              <span className="text-foreground font-semibold">1. Drop a paper.</span>{" "}
              Upload a CSV of the exam questions you want to check.
            </div>
            <div>
              <span className="text-foreground font-semibold">2. We scan the archive.</span>{" "}
              Every question is matched against our full historical archive in
              real time.
            </div>
            <div>
              <span className="text-foreground font-semibold">3. Read the report.</span>{" "}
              See exactly which questions already exist, which are close
              variations, and which are brand-new.
            </div>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="flex flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Recent runs</CardTitle>
              <CardDescription>Most recent five batch checks.</CardDescription>
            </div>
            <Link
              href="/batches"
              className={buttonVariants({ variant: "ghost", size: "sm", className: "text-[13px] font-medium" })}
            >
              View all
            </Link>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-9 w-full" />
                ))}
              </div>
            ) : !batches?.length ? (
              <div className="rounded-lg border border-dashed py-10 text-center text-[13.5px] text-muted-foreground">
                No batches yet — your first run will appear here.
              </div>
            ) : (
              <ul className="divide-y divide-border/70">
                {batches.map((b) => (
                  <li key={b.batch_id} className="flex items-center gap-3 py-2.5 text-[13.5px]">
                    <Link
                      href={`/batches/${b.batch_id}`}
                      className="flex flex-1 items-center gap-3 truncate"
                    >
                      <span className="truncate font-medium text-foreground">
                        {b.subject_name ? shortenSubject(b.subject_name) : "Mixed"}
                      </span>
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground tabular">
                        {fmtNumber(b.total)} q
                      </span>
                      <span className="text-muted-foreground tabular">
                        {fmtRelativeTime(b.ingested_at)}
                      </span>
                    </Link>
                    <div className="flex items-center gap-1.5">
                      {b.counts.REPEAT > 0 && <CountChip v="REPEAT" n={b.counts.REPEAT} />}
                      {b.counts.NEAR_HIGH > 0 && <CountChip v="NEAR_HIGH" n={b.counts.NEAR_HIGH} />}
                      {b.counts.NEAR > 0 && <CountChip v="NEAR" n={b.counts.NEAR} />}
                      {b.counts.NEW > 0 && <CountChip v="NEW" n={b.counts.NEW} />}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function CountChip({
  v,
  n,
}: {
  v: "REPEAT" | "NEAR_HIGH" | "NEAR" | "NEW";
  n: number;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <VerdictPill verdict={v} size="sm" forceTechnical />
      <span className="text-[11px] tabular text-muted-foreground">{n}</span>
    </span>
  );
}
