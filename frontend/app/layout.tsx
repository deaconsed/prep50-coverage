import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";

import { Providers } from "@/components/providers";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { InstantCheckDialog } from "@/components/instant-check-dialog";
import { QuestionDetailDialog } from "@/components/question-detail-dialog";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Prep50 Coverage — see what already lives in our archive",
  description:
    "Drop in any exam paper. Prep50 Coverage matches every question against tens of thousands of historical exam questions in our archive — instantly showing what already exists and what's truly new.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      style={{ ["--font-sans" as never]: "var(--font-geist-sans)" }}
      // next-themes flips the `.dark` class on <html> before hydration; this
      // tells React not to flag the resulting attribute diff as a mismatch.
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <Providers>
          {/*
            useSearchParams() (inside useTechnicalMode) bubbles up through
            multiple components — header, footer, every verdict pill, the
            dialogs. Next.js 16's strict static prerender rejects the build
            unless they're inside a Suspense boundary, so we wrap the whole
            tree once at the root.
          */}
          <Suspense fallback={null}>
            <SiteHeader />
            <main className="flex-1 w-full">{children}</main>
            <SiteFooter />
            <InstantCheckDialog />
            <QuestionDetailDialog />
          </Suspense>
        </Providers>
      </body>
    </html>
  );
}
