import { Check } from "lucide-react";

export type StepperKey = "upload" | "processing" | "done";

const STEPS: { key: StepperKey; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "processing", label: "Check" },
  { key: "done", label: "Review" },
];

/** Pill stepper with connector lines. Mirrors the Streamlit polish pass. */
export function Stepper({ current }: { current: StepperKey }) {
  const curIdx = STEPS.findIndex((s) => s.key === current);
  return (
    <div className="flex items-center gap-1 text-[13.5px] font-semibold">
      {STEPS.map((step, i) => {
        const state: "done" | "active" | "pending" =
          i < curIdx ? "done" : i === curIdx ? "active" : "pending";
        return (
          <div key={step.key} className="flex items-center gap-1">
            <div
              className={[
                "flex items-center gap-2.5 rounded-full border px-4 py-2 shadow-sm transition-colors",
                state === "active"
                  ? "border-[var(--brand)] bg-[var(--brand)] text-[var(--brand-foreground)]"
                  : state === "done"
                  ? "border-[var(--brand-soft)] bg-[var(--brand-tint)] text-[var(--brand-deep)]"
                  : "border-border bg-card text-muted-foreground",
              ].join(" ")}
            >
              <span
                className={[
                  "flex h-[22px] w-[22px] items-center justify-center rounded-full text-[12px] font-bold",
                  state === "active"
                    ? "bg-white/25 text-[var(--brand-foreground)]"
                    : state === "done"
                    ? "bg-[var(--brand)] text-white"
                    : "bg-muted text-muted-foreground",
                ].join(" ")}
              >
                {state === "done" ? <Check className="h-3 w-3" /> : i + 1}
              </span>
              {step.label}
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={[
                  "h-[2px] w-9",
                  state === "done"
                    ? "bg-[var(--brand-soft)]"
                    : "bg-border",
                ].join(" ")}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
