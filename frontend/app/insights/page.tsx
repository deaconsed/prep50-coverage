"use client";

import { useEffect, useMemo, useState } from "react";
import { BarChart3, Check, Search } from "lucide-react";

import { SmartText } from "@/components/smart-text";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useInsightQuestions,
  useInsightSubjects,
  useInsightTopics,
  type InsightQuestionQuery,
} from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import type { TopicStat } from "@/lib/types";

type Exam = "all" | "waec" | "utme" | "both";

const EXAM_META: Record<number, { label: string; cls: string }> = {
  0: { label: "WAEC", cls: "border-amber-300/60 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300" },
  1: { label: "UTME", cls: "border-emerald-300/60 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300" },
  2: { label: "WAEC + UTME", cls: "border-violet-300/60 bg-violet-50 text-violet-700 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-300" },
};

const EXAM_FILTERS: { key: Exam; label: string }[] = [
  { key: "all", label: "All" },
  { key: "waec", label: "WAEC" },
  { key: "utme", label: "UTME" },
  { key: "both", label: "Both" },
];

// Archive tagging noise we never want to surface as a "topic".
const JUNK = /^(unsorted|accounts of non-for-profit|jamb )/i;

/** Fix mojibake + title-case ALL-CAPS topic labels for display. */
function prettyTopic(s: string): string {
  let t = s
    .replace(/â€™|â€™/g, "'")
    .replace(/â€"/g, "–")
    .replace(/â€œ|â€/g, '"')
    .replace(/\s+/g, " ")
    .trim();
  if (/[A-Z]/.test(t) && t === t.toUpperCase()) {
    t = t.toLowerCase().replace(/\b([a-z])/g, (_, c: string) => c.toUpperCase());
  }
  return t;
}

export default function InsightsPage() {
  const { data: subjects, isLoading: subjectsLoading } = useInsightSubjects();

  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [exam, setExam] = useState<Exam>("all");
  const [year, setYear] = useState<number | null>(null);

  // Default to the richest subject once the list arrives.
  useEffect(() => {
    if (subjectId == null && subjects?.length) setSubjectId(subjects[0].id);
  }, [subjects, subjectId]);

  const { data: topics, isLoading: topicsLoading } = useInsightTopics(subjectId);

  const cleanTopics = useMemo<TopicStat[]>(
    () => (topics ?? []).filter((t) => !JUNK.test(t.topic.trim())),
    [topics],
  );

  // Reset drill-down state whenever the subject changes.
  useEffect(() => {
    setTopic(null);
    setSearch("");
    setExam("all");
    setYear(null);
  }, [subjectId]);

  // Default to the top topic for the current subject.
  useEffect(() => {
    if (topic == null && cleanTopics.length) setTopic(cleanTopics[0].topic);
  }, [cleanTopics, topic]);

  const visibleTopics = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return cleanTopics;
    return cleanTopics.filter((t) => prettyTopic(t.topic).toLowerCase().includes(q));
  }, [cleanTopics, search]);

  const qQuery: InsightQuestionQuery | null =
    subjectId != null && topic ? { subjectId, topic, exam, year, limit: 60 } : null;
  const { data: questions, isFetching } = useInsightQuestions(qQuery);

  const activeSubject = subjects?.find((s) => s.id === subjectId) ?? null;
  const activeTopicStat = cleanTopics.find((t) => t.topic === topic) ?? null;

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8 sm:py-10 space-y-8">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full bg-[var(--brand-tint)] px-3 py-1 text-[12px] font-semibold text-[var(--brand-deep)]">
          <BarChart3 className="h-3.5 w-3.5" />
          Coverage Insights
        </div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">
          What WAEC &amp; UTME keep asking
        </h1>
        <p className="max-w-2xl text-[14.5px] leading-relaxed text-muted-foreground">
          Browse the archive by topic. Open any topic to read the real past questions behind
          the numbers — filter by exam or year, with the correct answer marked. Every question
          is drawn live from the Prep50 archive.
        </p>
      </header>

      {/* ── Subject picker ─────────────────────────────────────── */}
      <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        {subjectsLoading
          ? Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-28 shrink-0 rounded-full" />
            ))
          : (subjects ?? []).map((s) => {
              const active = s.id === subjectId;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSubjectId(s.id)}
                  className={[
                    "shrink-0 rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                    active
                      ? "border-transparent bg-[var(--brand)] text-[var(--brand-foreground)]"
                      : "border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted",
                  ].join(" ")}
                >
                  {s.name}
                  <span
                    className={[
                      "ml-2 tabular text-[11px]",
                      active ? "text-[var(--brand-foreground)]/80" : "text-muted-foreground/70",
                    ].join(" ")}
                  >
                    {fmtNumber(s.total)}
                  </span>
                </button>
              );
            })}
      </div>

      {/* ── Explorer ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        {/* Topic rail */}
        <aside className="space-y-3 lg:sticky lg:top-20 lg:self-start">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search topics…"
              className="h-10 rounded-xl pl-9"
            />
          </div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
            {topicsLoading ? "Topics" : `${visibleTopics.length} topic${visibleTopics.length !== 1 ? "s" : ""}`}
            {activeSubject?.year_min ? (
              <span className="ml-1 font-normal normal-case tracking-normal">
                · {activeSubject.year_min}–{activeSubject.year_max}
              </span>
            ) : null}
          </div>
          <div className="max-h-[70vh] space-y-1 overflow-y-auto pr-1 lg:max-h-[calc(100vh-13rem)]">
            {topicsLoading
              ? Array.from({ length: 12 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full rounded-lg" />
                ))
              : visibleTopics.map((t) => {
                  const active = t.topic === topic;
                  const split = t.ssce + t.utme || 1;
                  return (
                    <button
                      key={t.topic}
                      type="button"
                      onClick={() => {
                        setTopic(t.topic);
                        setExam("all");
                        setYear(null);
                      }}
                      className={[
                        "w-full rounded-lg border px-3 py-2.5 text-left transition-colors",
                        active
                          ? "border-[var(--brand)]/40 bg-[var(--brand-tint)]"
                          : "border-transparent hover:bg-muted",
                      ].join(" ")}
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span
                          className={[
                            "text-[13.5px] font-medium leading-snug",
                            active ? "text-[var(--brand-deep)]" : "",
                          ].join(" ")}
                        >
                          {prettyTopic(t.topic)}
                        </span>
                        <span className="tabular shrink-0 text-[12px] font-semibold text-muted-foreground">
                          {fmtNumber(t.n)}
                        </span>
                      </div>
                      <div className="mt-1.5 flex items-center gap-2">
                        <span className="flex h-1 flex-1 overflow-hidden rounded-full bg-muted">
                          <span className="bg-amber-400 dark:bg-amber-500" style={{ width: `${(t.ssce / split) * 100}%` }} />
                          <span className="bg-emerald-400 dark:bg-emerald-500" style={{ width: `${(t.utme / split) * 100}%` }} />
                        </span>
                        {t.years > 0 && (
                          <span className="tabular shrink-0 text-[10.5px] text-muted-foreground/70">
                            {t.years} yrs
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
            {!topicsLoading && visibleTopics.length === 0 && (
              <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">
                No topics match “{search}”.
              </p>
            )}
          </div>
        </aside>

        {/* Question pane */}
        <section className="min-w-0 space-y-4">
          {/* Topic header */}
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="text-lg font-semibold tracking-tight">
              {topic ? prettyTopic(topic) : "Select a topic"}
            </h2>
            {activeTopicStat && (
              <span className="tabular text-[12.5px] text-muted-foreground">
                {fmtNumber(activeTopicStat.n)} in archive
                {questions && questions.total > (questions.items.length)
                  ? ` · showing ${questions.items.length} most recent`
                  : ""}
              </span>
            )}
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2 border-b border-border pb-4">
            <div className="inline-flex overflow-hidden rounded-lg border border-border">
              {EXAM_FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => {
                    setExam(f.key);
                    setYear(null);
                  }}
                  className={[
                    "border-r border-border px-3 py-1.5 text-[12.5px] font-medium transition-colors last:border-r-0",
                    exam === f.key
                      ? "bg-foreground text-background"
                      : "bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
                  ].join(" ")}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <select
              value={year ?? ""}
              onChange={(e) => setYear(e.target.value ? Number(e.target.value) : null)}
              className="h-8 rounded-lg border border-border bg-card px-2.5 text-[12.5px] font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Filter by year"
            >
              <option value="">All years</option>
              {(questions?.years ?? []).map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <span className="tabular ml-auto text-[12px] text-muted-foreground">
              {questions ? `${fmtNumber(questions.total)} question${questions.total !== 1 ? "s" : ""}` : ""}
            </span>
          </div>

          {/* Questions */}
          <div className={["space-y-3 transition-opacity", isFetching ? "opacity-60" : ""].join(" ")}>
            {!questions && (
              <>
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-32 w-full rounded-xl" />
                ))}
              </>
            )}
            {questions && questions.items.length === 0 && (
              <Card>
                <CardContent className="py-12 text-center text-[13.5px] text-muted-foreground">
                  No questions match these filters.
                </CardContent>
              </Card>
            )}
            {questions?.items.map((q) => {
              const meta = EXAM_META[q.exam] ?? EXAM_META[2];
              return (
                <Card key={q.id} className="overflow-hidden">
                  <CardContent className="space-y-3 p-4 sm:p-5">
                    <div className="flex items-center gap-2">
                      <span className="tabular rounded-md border border-border bg-muted/60 px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
                        {q.year ?? "Year n/a"}
                      </span>
                      <span className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${meta.cls}`}>
                        {meta.label}
                      </span>
                    </div>
                    <div className="text-[14.5px] leading-relaxed text-foreground">
                      <SmartText>{q.question}</SmartText>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {q.options.map((o, i) => {
                        const correct = q.answer === i + 1;
                        return (
                          <div
                            key={i}
                            className={[
                              "flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px] leading-snug",
                              correct
                                ? "border-emerald-400/70 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                                : "border-border bg-muted/40 text-muted-foreground",
                            ].join(" ")}
                          >
                            <span
                              className={[
                                "mt-px font-mono text-[11.5px] font-bold",
                                correct ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground/70",
                              ].join(" ")}
                            >
                              {String.fromCharCode(65 + i)}
                            </span>
                            <span className="min-w-0 flex-1">
                              <SmartText>{o ?? "—"}</SmartText>
                            </span>
                            {correct && <Check className="mt-px h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />}
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
            {questions && questions.total > questions.items.length && (
              <p className="pt-1 text-center text-[12px] italic text-muted-foreground/70">
                Showing the {questions.items.length} most recent of {fmtNumber(questions.total)} — refine by exam or year to see others.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
