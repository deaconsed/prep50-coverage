"use client";

import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useSubjects } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

interface Props {
  value: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
}

/**
 * Dropdown of W/JW subjects with per-subject corpus counts inline.
 * Hides subjects with zero corpus (nothing to check against).
 */
export function SubjectPicker({ value, onChange, disabled }: Props) {
  const { data, isLoading } = useSubjects();

  const handleChange = (v: string | null) => {
    onChange(v ? Number(v) : null);
  };

  return (
    <Select
      // Always pass a non-undefined value so the Select stays controlled
      // for its entire lifetime. base-ui accepts `null` for "no selection".
      value={value != null ? String(value) : null}
      onValueChange={handleChange}
      disabled={disabled || isLoading}
    >
      <SelectTrigger className="w-full h-11 rounded-xl">
        <SelectValue placeholder={isLoading ? "Loading subjects…" : "Choose a subject"} />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {(data ?? []).map((s) => (
            <SelectItem key={s.id} value={String(s.id)}>
              <span className="flex items-center gap-2">
                <span className="font-medium">{s.name}</span>
                <span className="text-[11px] rounded-full bg-muted px-2 py-0.5 font-semibold text-muted-foreground tabular">
                  {fmtNumber(s.corpus_count)} q
                </span>
                <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                  {s.tag}
                </span>
              </span>
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
