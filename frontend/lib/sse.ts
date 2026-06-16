/**
 * Server-Sent Events consumer for /api/batches/{id}/events.
 *
 * Browser EventSource ignores custom `event:` names unless you addEventListener
 * for each one, so we do that explicitly. Returns an unsubscribe function.
 *
 * Auto-close on `done` and `error`.
 */
import { API_BASE } from "./api";
import type { SseEvent } from "./types";

const EVENT_NAMES: SseEvent["event"][] = [
  "started",
  "phase",
  "intra_dups",
  "item",
  "done",
  "error",
  "ping",
];

export function streamBatchEvents(
  batchId: string,
  onEvent: (e: SseEvent) => void,
): () => void {
  const url = `${API_BASE}/api/batches/${batchId}/events`;
  const es = new EventSource(url);

  for (const name of EVENT_NAMES) {
    es.addEventListener(name, (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data);
        onEvent({ event: name, data } as SseEvent);
        if (name === "done" || name === "error") es.close();
      } catch {
        // Ignore malformed payloads; the server only emits JSON.
      }
    });
  }

  es.onerror = () => {
    // EventSource auto-reconnects by default. After `done` we close above,
    // so any remaining error here means the network blipped — let it retry.
  };

  return () => es.close();
}
