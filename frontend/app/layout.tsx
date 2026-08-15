import type { Metadata } from "next";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Quorum",
  description: "Agentic RAG over uploaded documents",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>
          <div className="min-h-screen">
            <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
              <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
                <Link href="/" className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  Quorum
                </Link>
                <nav className="flex items-center gap-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  <Link href="/eval" className="hover:text-slate-900 dark:hover:text-white">
                    Eval
                  </Link>
                  <Link href="/settings" className="hover:text-slate-900 dark:hover:text-white">
                    Settings
                  </Link>
                  <ThemeToggle />
                </nav>
              </div>
            </header>
            <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
