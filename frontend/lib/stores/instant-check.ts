/**
 * Tiny Zustand store for the global Instant-Check dialog visibility.
 * Lets the header button + the ⌘K shortcut + any page anchor open the same
 * dialog without prop-drilling.
 */
import { create } from "zustand";

interface InstantCheckState {
  open: boolean;
  setOpen: (next: boolean) => void;
  toggle: () => void;
}

export const useInstantCheck = create<InstantCheckState>((set) => ({
  open: false,
  setOpen: (next) => set({ open: next }),
  toggle: () => set((s) => ({ open: !s.open })),
}));
