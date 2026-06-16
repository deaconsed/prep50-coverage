/**
 * Technical-detail mode toggle.
 *
 * Resolution order (first wins):
 *   1. URL ?tech=1 / ?tech=0
 *   2. localStorage["prep50:tech"] = "1" | "0"
 *   3. NEXT_PUBLIC_SHOW_TECHNICAL env var (default "false")
 *
 * Hydration note: the initial useState value MUST match what the server
 * renders, so we deliberately ignore localStorage during the first render.
 * After mount, useEffect upgrades the state from localStorage if it diverges.
 * Skipping this causes server/client mismatch warnings on every page when
 * the user has previously toggled the setting.
 */
"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "prep50:tech";
const DEFAULT_ON = process.env.NEXT_PUBLIC_SHOW_TECHNICAL === "true";

function readFromUrlOrEnv(searchParam: string | null): boolean {
  if (searchParam === "1" || searchParam === "true") return true;
  if (searchParam === "0" || searchParam === "false") return false;
  return DEFAULT_ON;
}

function readFromStorage(): boolean | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "1") return true;
  if (stored === "0") return false;
  return null;
}

export function useTechnicalMode(): [boolean, (next: boolean) => void] {
  const sp = useSearchParams();
  const techParam = sp.get("tech");

  // Initial state uses ONLY values available on the server (env + URL). The
  // localStorage check is intentionally deferred to useEffect — otherwise
  // the SSR HTML and the first client render disagree and React aborts.
  const [on, setOn] = useState<boolean>(() => readFromUrlOrEnv(techParam));

  // After mount, prefer localStorage if it has a value and the URL hasn't
  // forced an override. Subsequent URL changes win.
  useEffect(() => {
    if (techParam === "1" || techParam === "true") {
      setOn(true);
      return;
    }
    if (techParam === "0" || techParam === "false") {
      setOn(false);
      return;
    }
    const stored = readFromStorage();
    if (stored !== null) setOn(stored);
    else setOn(DEFAULT_ON);
  }, [techParam]);

  // Cross-tab sync.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (ev: StorageEvent) => {
      if (ev.key !== STORAGE_KEY) return;
      const stored = readFromStorage();
      if (stored !== null) setOn(stored);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setMode = useCallback((next: boolean) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    }
    setOn(next);
  }, []);

  return [on, setMode];
}
