"use client";

import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { SideBySide } from "@/components/side-by-side";
import { SubjectPicker } from "@/components/subject-picker";
import { VerdictPill } from "@/components/verdict-pill";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { checkSingle } from "@/lib/api";
import { useInstantCheck } from "@/lib/stores/instant-check";
import type { SingleCheckResponse, Verdict } from "@/lib/types";

/**
 * Global dialog mounted once at the layout level.
 * Opened via the header CTA, `⌘K`, or `useInstantCheck.setOpen(true)`.
 */
export function InstantCheckDialog() {
  const { open, setOpen } = useInstantCheck();

  const [question, setQuestion] = useState("");
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SingleCheckResponse | null>(null);

  // Cmd/Ctrl + K shortcut
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  // Reset on close.
  useEffect(() => {
    if (!open) {
      setResult(null);
      setLoading(false);
    }
  }, [open]);

  async function handleCheck() {
    if (!question.trim() || subjectId == null) return;
    try {
      setLoading(true);
      const r = await checkSingle({ question: question.trim(), subject_id: subjectId });
      setResult(r);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Check failed");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setResult(null);
    setQuestion("");
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="w-[96vw] sm:!max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--brand)]" />
            Instant check
          </DialogTitle>
          <DialogDescription>
            Paste a single question, pick a subject, and check it against the corpus.
          </DialogDescription>
        </DialogHeader>

        {!result ? (
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Question
              </label>
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Paste the full question text here. Options aren't needed for the check."
                rows={5}
                disabled={loading}
                className="w-full resize-y rounded-xl border bg-card px-4 py-3 text-[14px] leading-relaxed shadow-sm outline-none transition-colors focus:border-[var(--brand)] focus:ring-2 focus:ring-[var(--brand-tint)]"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Subject
              </label>
              <SubjectPicker value={subjectId} onChange={setSubjectId} disabled={loading} />
            </div>
            <DialogFooter className="pt-2">
              <Button
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={loading}
                className="rounded-full"
              >
                Cancel
              </Button>
              <Button
                onClick={handleCheck}
                disabled={loading || !question.trim() || subjectId == null}
                className="rounded-full px-5"
              >
                {loading ? "Checking…" : "Check now"}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <VerdictPill verdict={result.verdict as Verdict} />
              <div className="text-[12.5px] text-muted-foreground">{result.reason}</div>
            </div>
            <SideBySide
              newInput={result.input}
              match={
                result.verdict === "REPEAT" && result.fingerprint_matches.length > 0
                  ? result.fingerprint_matches[0]
                  : result.top_k[0] ?? null
              }
              kind={
                result.verdict === "REPEAT"
                  ? "fingerprint"
                  : result.top_k.length > 0
                  ? "cosine"
                  : null
              }
              cosine={
                result.verdict !== "REPEAT" && result.top_k.length > 0
                  ? result.top_k[0].cosine
                  : undefined
              }
            />
            <DialogFooter className="pt-2">
              <Button
                variant="outline"
                onClick={handleReset}
                className="rounded-full"
              >
                Check another
              </Button>
              <Button onClick={() => setOpen(false)} className="rounded-full px-5">
                Close
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
