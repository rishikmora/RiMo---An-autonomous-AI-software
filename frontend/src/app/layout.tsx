import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "RiMo — Autonomous Software Company",
  description:
    "RiMo is an autonomous AI software engineering company: ten specialist agents that plan, build, review, test, and ship software around the clock.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen bg-void font-sans antialiased">{children}</body>
    </html>
  );
}
