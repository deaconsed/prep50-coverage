/**
 * Singleton store for the question-detail modal.
 *
 * Holds a window over an items array so the modal can walk forward/back
 * without closing. The page passes whatever list the user is currently
 * looking at (already filtered) — that way Next/Prev follow the user's
 * filter state.
 */
import { create } from "zustand";

import type { VerdictItem } from "@/lib/types";

interface QuestionDetailState {
  items: VerdictItem[];
  position: number;
  total: number;
  open: (items: VerdictItem[], position: number, total: number) => void;
  next: () => void;
  prev: () => void;
  goTo: (position: number) => void;
  close: () => void;
}

export const useQuestionDetail = create<QuestionDetailState>((set, get) => ({
  items: [],
  position: 0,
  total: 0,
  open: (items, position, total) =>
    set({
      items,
      position: clamp(position, 0, Math.max(items.length - 1, 0)),
      total,
    }),
  next: () => {
    const { items, position } = get();
    if (position < items.length - 1) set({ position: position + 1 });
  },
  prev: () => {
    const { position } = get();
    if (position > 0) set({ position: position - 1 });
  },
  goTo: (position) => {
    const { items } = get();
    set({ position: clamp(position, 0, Math.max(items.length - 1, 0)) });
  },
  close: () => set({ items: [], position: 0, total: 0 }),
}));

function clamp(n: number, lo: number, hi: number) {
  return Math.min(Math.max(n, lo), hi);
}
