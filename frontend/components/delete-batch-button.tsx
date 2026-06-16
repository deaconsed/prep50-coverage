"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type MouseEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { deleteBatch } from "@/lib/api";

interface Props {
  batchId: string;
  subjectName?: string | null;
  total?: number;
  /** Where to send the user after a successful delete (history detail uses /batches). */
  redirectTo?: string;
  /** "icon" — small trash icon. "labeled" — outlined button with text. */
  variant?: "icon" | "labeled";
}

/**
 * Destructive action wrapped in a two-step confirmation dialog.
 *
 * Click handlers stop event propagation because the parent row is typically a
 * <Link> — we never want the row to navigate when the user is reaching for
 * the trash icon.
 */
export function DeleteBatchButton({
  batchId,
  subjectName,
  total,
  redirectTo,
  variant = "icon",
}: Props) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const router = useRouter();
  const qc = useQueryClient();

  function stop(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
  }

  async function handleDelete() {
    try {
      setDeleting(true);
      await deleteBatch(batchId);
      toast.success("Batch deleted");
      await qc.invalidateQueries({ queryKey: ["batches"] });
      qc.removeQueries({ queryKey: ["batches", batchId] });
      setOpen(false);
      if (redirectTo) router.push(redirectTo);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      {variant === "icon" ? (
        <button
          type="button"
          onClick={(e) => {
            stop(e);
            setOpen(true);
          }}
          title="Delete batch"
          className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-[var(--verdict-repeat-bg)] hover:text-[var(--verdict-repeat-fg)] transition-colors"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      ) : (
        <Button
          variant="outline"
          size="sm"
          onClick={(e) => {
            stop(e);
            setOpen(true);
          }}
          className="rounded-full text-[var(--verdict-repeat-fg)] hover:bg-[var(--verdict-repeat-bg)] hover:text-[var(--verdict-repeat-fg)]"
        >
          <Trash2 className="mr-1.5 h-3.5 w-3.5" />
          Delete
        </Button>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[96vw] sm:!max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this batch?</DialogTitle>
            <DialogDescription>
              {total
                ? `This will permanently remove the ${total}-question report${
                    subjectName ? ` for ${subjectName}` : ""
                  }.`
                : "This will permanently remove the batch report."}{" "}
              The action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              variant="outline"
              onClick={(e) => {
                stop(e);
                setOpen(false);
              }}
              disabled={deleting}
              className="rounded-full"
            >
              Cancel
            </Button>
            <Button
              onClick={(e) => {
                stop(e);
                handleDelete();
              }}
              disabled={deleting}
              className="rounded-full bg-[var(--verdict-repeat)] text-white hover:bg-[var(--verdict-repeat)]/90"
            >
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
