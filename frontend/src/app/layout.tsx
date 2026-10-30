import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppProviders } from "@/components/providers/app-providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "FlowPilot AI | Multi-Agent Workflow Orchestration Platform",
  description:
    "Production multi-agent execution platform with human-in-the-loop approvals, Multi-LLM BYOK, and external enterprise integrations.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full">
      <body className={`${inter.className} min-h-full flex flex-col antialiased`}>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
