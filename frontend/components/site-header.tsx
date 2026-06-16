"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, Layers, History, Sparkles } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { useInstantCheck } from "@/lib/stores/instant-check";

const NAV = [
  { href: "/", label: "Overview", icon: Sparkles },
  { href: "/check", label: "New check", icon: Layers },
  { href: "/batches", label: "History", icon: History },
];

export function SiteHeader() {
  const pathname = usePathname();
  const openInstantCheck = useInstantCheck((s) => s.setOpen);
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-6">
        <Link
          href="/"
          className="flex items-center gap-2 text-[15px] font-semibold tracking-tight"
        >
          <span
            aria-hidden
            className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--brand)] text-[var(--brand-foreground)] text-[13px] font-bold shadow-sm shadow-[color-mix(in_oklab,var(--brand),transparent_60%)]"
          >
            P
          </span>
          Prep50
          <span className="hidden text-muted-foreground text-[13px] font-normal sm:inline">
            · Coverage
          </span>
        </Link>

        <nav className="ml-auto flex items-center gap-1 text-[13.5px]">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname?.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={[
                  "inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-medium transition-colors",
                  active
                    ? "bg-[var(--brand-tint)] text-[var(--brand-deep)]"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted",
                ].join(" ")}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => openInstantCheck(true)}
            className={buttonVariants({
              variant: "outline",
              size: "sm",
              className: "ml-2 h-8 gap-1.5 rounded-full text-[13px] font-medium",
            })}
          >
            <Search className="h-3.5 w-3.5" />
            Instant check
            <span className="ml-1 hidden rounded border bg-muted/60 px-1 py-0 text-[10.5px] text-muted-foreground sm:inline">
              ⌘K
            </span>
          </button>
        </nav>
      </div>
    </header>
  );
}
