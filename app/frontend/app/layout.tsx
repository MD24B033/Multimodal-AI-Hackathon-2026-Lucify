import type { Metadata } from "next";
import { Bricolage_Grotesque, Inter } from "next/font/google";

import { AppFrame } from "@/components/app-frame";
import { SessionProvider } from "@/components/session-context";
import { TaskProvider } from "@/components/task-center";
import "katex/dist/katex.min.css";
import "./globals.css";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Lucify — source-grounded study companion",
  description:
    "Turns lecture videos, textbooks and slides into a cited knowledge base, then tutors and assesses you from it.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <body className={`${display.variable} ${sans.variable} antialiased`}>
        <SessionProvider>
          <TaskProvider>
            <AppFrame>{children}</AppFrame>
          </TaskProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
