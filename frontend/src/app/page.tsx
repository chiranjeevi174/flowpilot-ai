"use client";

import React, { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Bot, CheckCircle2, Shield, Sparkles, Zap } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && user) {
      router.push("/dashboard");
    }
  }, [user, isLoading, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">Initializing FlowPilot AI...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-background selection:bg-primary/20">
      {/* Navigation */}
      <header className="flex h-16 items-center justify-between border-b border-border bg-card/80 backdrop-blur-md px-6 md:px-12 sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Zap className="h-4 w-4 fill-current text-white" />
          </div>
          <div className="flex flex-col">
            <span className="font-bold text-base tracking-tight text-foreground leading-tight">
              FlowPilot AI
            </span>
            <span className="text-[10px] text-muted-foreground font-mono tracking-wider uppercase">
              Modern Enterprise
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/login">
            <Button variant="ghost" size="sm" className="text-xs">Sign In</Button>
          </Link>
          <Link href="/register">
            <Button size="sm" className="text-xs">Get Started</Button>
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-20 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5 text-xs font-medium text-foreground mb-8 shadow-xs">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span>Multi-Agent Workflow Orchestration &amp; Business Automation</span>
        </div>

        <h1 className="max-w-4xl text-4xl sm:text-6xl font-extrabold tracking-tight text-foreground leading-[1.15] mb-6">
          Autonomous Agents for{" "}
          <span className="text-primary">
            Enterprise Operations
          </span>
        </h1>

        <p className="max-w-2xl text-base sm:text-lg text-muted-foreground mb-10 leading-relaxed">
          FlowPilot AI coordinates LangGraph multi-agent planning with durable Celery execution,
          cryptographic human-in-the-loop approvals, Multi-LLM BYOK, and production integrations with Gmail,
          WhatsApp, Slack, and Google Sheets.
        </p>

        <div className="flex flex-col sm:flex-row gap-4 mb-16">
          <Link href="/register">
            <Button size="lg" className="w-full sm:w-auto h-11 px-8 text-sm shadow-sm">
              Launch Workspace
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </Link>
          <Link href="/login">
            <Button size="lg" variant="outline" className="w-full sm:w-auto h-11 px-8 text-sm">
              Operator Sign In
            </Button>
          </Link>
        </div>

        {/* Feature Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl text-left w-full">
          <div className="rounded-xl border border-border bg-card p-6 shadow-xs transition hover:border-primary/40">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary mb-4">
              <Bot className="h-5 w-5" />
            </div>
            <h3 className="font-semibold text-foreground text-base mb-1.5">Multi-Agent Planning</h3>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Intent analysis, step planning, deterministic tool routing, and verification nodes
              backed by LangGraph checkpointing.
            </p>
          </div>

          <div className="rounded-xl border border-border bg-card p-6 shadow-xs transition hover:border-[#16866B]/40">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#16866B]/10 text-[#16866B] mb-4">
              <Shield className="h-5 w-5" />
            </div>
            <h3 className="font-semibold text-foreground text-base mb-1.5">Human-in-the-Loop</h3>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Mandatory cryptographic approval gates for sensitive actions like sending emails,
              dispatching WhatsApp messages, and spreadsheet writes.
            </p>
          </div>

          <div className="rounded-xl border border-border bg-card p-6 shadow-xs transition hover:border-primary/40">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary mb-4">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <h3 className="font-semibold text-foreground text-base mb-1.5">Durable Idempotency</h3>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Transactional outbox dispatch, Redis Celery workers, automatic recovery, and external
              action replay deduplication.
            </p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border py-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} FlowPilot AI Platform. Modern Enterprise Multi-Agent Architecture.
      </footer>
    </div>
  );
}
