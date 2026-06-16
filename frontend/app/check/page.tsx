"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { CoverageBanner } from "@/components/coverage-banner";
import { CsvPreview } from "@/components/csv-preview";
import { LiveCharts } from "@/components/live-charts";
import { Stepper, type StepperKey } from "@/components/stepper";
import { SubjectPicker } from "@/components/subject-picker";
import { SummaryTiles } from "@/components/summary-tiles";
import { UploadZone } from "@/components/upload-zone";
import { VerdictCard } from "@/components/verdict-card";
import { VerdictDonut } from "@/components/verdict-donut";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createBatch, useSubjects } from "@/lib/api";
import { useBatchEvents } from "@/lib/hooks/use-batch-events";
import { fmtNumber } from "@/lib/format";
import type { Verdict } from "@/lib/types";

type Phase = "upload" | "running" | "done";

export default function CheckPage() {
  const [file, setFile] = useState<File | null>(null);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>("upload");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [filter, setFilter] = useState<Verdict | "ALL">("ALL");

  const { data: subjects } = useSubjects();
  const subject = subjects?.find((s) => s.id === subjectId) ?? null;

  const batch = useBatchEvents(batchId);

  if (phase === "running" && batch.phase === "done") setPhase("done");

  const stepper: StepperKey =
    phase === "upload" ? "upload" : phase === "running" ? "processing" : "done";

  // Items come in newest-first; for filtering UX we render that order.
  const filteredItems = useMemo(
    () =>
      filter === "ALL"
        ? batch.items
        : batch.items.filter((it) => it.verdict === filter),
    [batch.items, filter],
  );

  // Summary fallback for the live "done" view — use the SSE-emitted summary if
  // present, otherwise derive from running counts.
  const liveSummary = batch.summary ?? {
    total: batch.total,
    ...batch.counts,
    by_subject: {},
    intra_batch_duplicate_groups: batch.intraDups.length,
  };

  async function handleStart() {
    if (!file || subjectId == null) return;
    try {
      setSubmitting(true);
      const created = await createBatch(file, subjectId);
      setBatchId(created.batch_id);
      setPhase("running");
      setFilter("ALL");
      toast.success(
        `Checking ${fmtNumber(created.total_questions)} questions against ${created.subject_name}`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start the batch");
    } finally {
      setSubmitting(false);
    }
  }

  function handleReset() {
    setFile(null);
    setSubjectId(null);
    setBatchId(null);
    setFilter("ALL");
    setPhase("upload");
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8 sm:py-10 space-y-8">
      <header className="flex items-center justify-between gap-6">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            New check
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Match a new exam paper</h1>
        </div>
        <Stepper current={stepper} />
      </header>

      <AnimatePresence mode="wait">
        {phase === "upload" && (
          <motion.div
            key="upload"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="grid grid-cols-1 gap-5 lg:grid-cols-5"
          >
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle className="text-base">Upload exam paper</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <UploadZone file={file} onFile={setFile} disabled={submitting} />
                <CsvPreview file={file} />
                <div>
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    Subject
                  </div>
                  <SubjectPicker
                    value={subjectId}
                    onChange={setSubjectId}
                    disabled={submitting}
                  />
                </div>
                <div className="flex items-center justify-between pt-2">
                  <span className="text-[12.5px] text-muted-foreground">
                    {file && subject ? (
                      <>
                        Ready to check against{" "}
                        <span className="font-semibold text-foreground">
                          {fmtNumber(subject.corpus_count)}
                        </span>{" "}
                        historical {subject.name} questions.
                      </>
                    ) : (
                      "Drop a CSV and pick a subject to continue."
                    )}
                  </span>
                  <button
                    type="button"
                    disabled={!file || subjectId == null || submitting}
                    onClick={handleStart}
                    className={buttonVariants({
                      size: "lg",
                      className:
                        "rounded-full px-6 disabled:opacity-50 disabled:cursor-not-allowed",
                    })}
                  >
                    {submitting ? "Starting…" : "Run coverage check"}
                  </button>
                </div>
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base">CSV format</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-[13.5px] text-muted-foreground leading-relaxed">
                <p>
                  One question per row. The only required column is{" "}
                  <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">
                    question
                  </code>
                  . These columns are also read when present:
                </p>
                <ul className="space-y-1.5 pl-4 list-disc text-[13px]">
                  <li>
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">
                      question_year
                    </code>{" "}
                    — original year, if known
                  </li>
                  <li>
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">
                      option_1
                    </code>{" "}
                    …{" "}
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">
                      option_4
                    </code>
                  </li>
                  <li>
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">
                      short_answer
                    </code>
                  </li>
                  <li>
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">
                      id
                    </code>{" "}
                    — your internal identifier
                  </li>
                </ul>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {(phase === "running" || phase === "done") && (
          <motion.div
            key="running"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="space-y-6"
          >
            {/* Live: charts + tally. Done: coverage banner + filter tiles + donut. */}
            {phase === "running" ? (
              <LiveCharts
                counts={batch.counts}
                done={batch.items.length}
                total={batch.total}
                phase={batch.phase}
                throughput={batch.throughput}
              />
            ) : (
              <>
                <CoverageBanner summary={liveSummary} subjectName={subject?.name} />
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="md:col-span-2 rounded-2xl border bg-card p-5 shadow-sm">
                    <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-3">
                      Filter results
                    </div>
                    <SummaryTiles
                      counts={batch.counts}
                      filter={filter}
                      onFilter={setFilter}
                    />
                  </div>
                  <div className="rounded-2xl border bg-card p-5 shadow-sm">
                    <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      Distribution
                    </div>
                    <VerdictDonut counts={batch.counts} height={180} />
                  </div>
                </div>
              </>
            )}

            {batch.intraDups.length > 0 && (
              <div className="rounded-xl border border-[var(--verdict-near-high-bg)] bg-[var(--verdict-near-high-bg)]/60 px-4 py-3 text-[13.5px] text-[var(--verdict-near-high-fg)]">
                <span className="font-semibold">Heads-up:</span> {batch.intraDups.length}{" "}
                repeated question group
                {batch.intraDups.length === 1 ? "" : "s"} detected — the same question
                appears more than once in your CSV.
              </div>
            )}

            {batch.error && (
              <div className="rounded-xl border border-[var(--verdict-repeat-bg)] bg-[var(--verdict-repeat-bg)]/60 px-4 py-3 text-[13.5px] text-[var(--verdict-repeat-fg)]">
                <span className="font-semibold">Run failed:</span> {batch.error}
              </div>
            )}

            <div className="flex items-center justify-between">
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                {phase === "done" ? (
                  <>
                    Results
                    {filter !== "ALL" && (
                      <span className="ml-2 normal-case tracking-normal text-[12.5px] text-muted-foreground">
                        filtered · {fmtNumber(filteredItems.length)}
                        <button
                          type="button"
                          onClick={() => setFilter("ALL")}
                          className="ml-1 underline hover:no-underline"
                        >
                          clear
                        </button>
                      </span>
                    )}
                  </>
                ) : (
                  "Results · live stream"
                )}
              </div>
              {phase === "done" && (
                <button
                  type="button"
                  onClick={handleReset}
                  className={buttonVariants({
                    variant: "outline",
                    size: "sm",
                    className: "rounded-full",
                  })}
                >
                  Run another check
                </button>
              )}
            </div>

            <div className="space-y-3">
              <AnimatePresence initial={false}>
                {filteredItems.map((it, i) => (
                  <VerdictCard
                    key={`${it.input_index}-${i}`}
                    item={it}
                    index={it.input_index}
                    total={batch.total}
                    items={filteredItems}
                    position={i}
                  />
                ))}
              </AnimatePresence>
              {filteredItems.length === 0 && batch.phase !== "error" && (
                <div className="rounded-2xl border border-dashed py-16 text-center text-[13.5px] text-muted-foreground">
                  {phase === "done"
                    ? "No items in this filter."
                    : "Waiting for the first result…"}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
