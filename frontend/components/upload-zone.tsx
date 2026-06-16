"use client";

import { Upload, FileText, X } from "lucide-react";
import { useDropzone } from "react-dropzone";
import { useCallback } from "react";

interface Props {
  file: File | null;
  onFile: (f: File | null) => void;
  disabled?: boolean;
}

/**
 * Drag-and-drop file uploader for the CSV.
 * Limits to .csv (we still handle cp1252 etc. server-side).
 */
export function UploadZone({ file, onFile, disabled }: Props) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length > 0) onFile(accepted[0]);
    },
    [onFile],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"], "application/vnd.ms-excel": [".csv"] },
    multiple: false,
    disabled: disabled || !!file,
  });

  if (file) {
    return (
      <div className="flex items-center gap-4 rounded-2xl border bg-card p-5 shadow-sm">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--brand-tint)] text-[var(--brand)]">
          <FileText className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="truncate text-[14px] font-semibold">{file.name}</div>
          <div className="text-[12px] tabular text-muted-foreground">
            {(file.size / 1024).toFixed(1)} KB · ready to upload
          </div>
        </div>
        <button
          type="button"
          onClick={() => onFile(null)}
          disabled={disabled}
          className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div
      {...getRootProps()}
      className={[
        "group relative flex min-h-[200px] cursor-pointer items-center justify-center rounded-2xl border-2 border-dashed bg-card/40 p-6 text-center transition-all",
        isDragActive
          ? "border-[var(--brand)] bg-[var(--brand-tint)] scale-[1.005]"
          : "border-border hover:border-[var(--brand)] hover:bg-[var(--brand-tint)]/30",
        disabled ? "opacity-50 cursor-not-allowed" : "",
      ].join(" ")}
    >
      <input {...getInputProps()} />
      <div className="flex flex-col items-center gap-3">
        <div
          className={[
            "flex h-12 w-12 items-center justify-center rounded-xl transition-transform",
            isDragActive ? "bg-[var(--brand)] text-white scale-105" : "bg-muted text-muted-foreground group-hover:bg-[var(--brand-tint)] group-hover:text-[var(--brand)]",
          ].join(" ")}
        >
          <Upload className="h-5 w-5" />
        </div>
        <div>
          <div className="text-[15px] font-semibold">
            {isDragActive ? "Drop the CSV here" : "Drop a CSV here, or click to browse"}
          </div>
          <div className="mt-1 text-[12.5px] text-muted-foreground">
            Excel CSV is fine — we auto-detect cp1252 / utf-8 / latin-1 encodings.
          </div>
        </div>
      </div>
    </div>
  );
}
