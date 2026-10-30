"use client";

import React from "react";
import { useRouter } from "next/navigation";
import {
  Clock,
  ShieldAlert,
  Play,
  ArrowRight,
  X,
  Loader2,
} from "lucide-react";
import { useNotifications } from "@/lib/notifications/notification-context";
import { Button } from "@/components/ui/button";

export function GlobalNotificationBanner() {
  const router = useRouter();
  const {
    activeCountdown,
    activeApprovalAlert,
    dismissActiveCountdown,
    dismissActiveApproval,
  } = useNotifications();

  if (!activeCountdown && !activeApprovalAlert) {
    return null;
  }

  return (
    <aside
      aria-label="Live workflow notifications"
      className="fixed bottom-6 right-6 z-40 flex flex-col gap-3 w-full max-w-sm pointer-events-none"
    >
      {/* 1. Live 15-Second Pre-Execution Countdown Card */}
      {activeCountdown && (
        <div className="pointer-events-auto rounded-xl border border-[#365650] bg-[#1E3733] text-[#F5F8F6] p-4 shadow-2xl animate-in slide-in-from-top-4 duration-300 overflow-hidden relative">
          {/* Top Header */}
          <div className="flex items-start justify-between gap-2 pb-2 border-b border-[#365650]/60">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#1F3A36] text-[#66C4AE] border border-[#365650]">
                {activeCountdown.state === "started" ? (
                  <Play className="h-3 w-3 fill-current" />
                ) : (
                  <Clock className="h-3.5 w-3.5" />
                )}
              </span>
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#66C4AE]">
                  {activeCountdown.state === "started"
                    ? "Workflow Started"
                    : activeCountdown.state === "due"
                    ? "Starting Shortly"
                    : "Upcoming Workflow"}
                </span>
                <p className="text-xs font-semibold text-[#F5F8F6] truncate max-w-[220px]">
                  {activeCountdown.scheduleName}
                </p>
              </div>
            </div>

            <button
              onClick={dismissActiveCountdown}
              className="text-[#C3D5D0] hover:text-[#F5F8F6] transition-colors p-1 rounded-md hover:bg-[#30534D]"
              aria-label="Dismiss countdown notification"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* Body Content */}
          <div className="py-3 space-y-2.5">
            {activeCountdown.state === "countdown" ? (
              <>
                <p className="text-[11px] text-[#C3D5D0]">
                  Your scheduled workflow is approaching its execution time.
                </p>

                {/* Tabular Numerals Countdown Display */}
                <div className="grid grid-cols-2 gap-2 bg-[#172B28] p-2.5 rounded-lg border border-[#365650]/70 text-center">
                  <div>
                    <span className="text-[9px] uppercase tracking-wider text-[#C3D5D0] block">
                      Execution begins in
                    </span>
                    <span className="font-mono text-xl font-bold tracking-tight text-[#66C4AE] tabular-nums">
                      00:{String(activeCountdown.remainingSeconds).padStart(2, "0")}
                    </span>
                  </div>
                  <div className="border-l border-[#365650]/50 pl-2">
                    <span className="text-[9px] uppercase tracking-wider text-[#C3D5D0] block">
                      Scheduled for
                    </span>
                    <span className="font-mono text-xs font-semibold text-[#F5F8F6] leading-7">
                      {activeCountdown.formattedScheduledTime}
                    </span>
                  </div>
                </div>

                {/* Synchronized Progress Bar */}
                <div className="w-full bg-[#172B28] rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-[#66C4AE] h-full transition-all duration-1000 ease-linear rounded-full"
                    style={{
                      width: `${Math.min(100, Math.max(0, (activeCountdown.remainingSeconds / 15) * 100))}%`,
                    }}
                  />
                </div>
              </>
            ) : activeCountdown.state === "due" ? (
              <div className="space-y-2 py-1 text-center">
                <div className="flex items-center justify-center gap-2 text-xs font-semibold text-[#66C4AE]">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Scheduled Time Reached</span>
                </div>
                <p className="text-[11px] text-[#C3D5D0]">
                  Dispatching multi-agent workflow to background orchestrator...
                </p>
              </div>
            ) : (
              <div className="space-y-3 py-1">
                <p className="text-[11px] text-[#C3D5D0]">
                  Scheduled run has launched and entered execution queue.
                </p>
                {activeCountdown.runId && (
                  <Button
                    size="sm"
                    className="w-full h-8 text-xs bg-[#087F72] hover:bg-[#066B5F] text-[#F5F8F6]"
                    onClick={() => {
                      dismissActiveCountdown();
                      router.push(`/executions/${activeCountdown.runId}`);
                    }}
                  >
                    <span>View Execution</span>
                    <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 2. Pending Human Approval Notification Card */}
      {activeApprovalAlert && (
        <div className="pointer-events-auto rounded-xl border border-amber-500/40 bg-card text-card-foreground p-4 shadow-2xl animate-in slide-in-from-top-4 duration-300">
          <div className="flex items-start justify-between gap-2 pb-2 border-b border-border">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400">
                <ShieldAlert className="h-4 w-4" />
              </span>
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400">
                  Approval Required
                </span>
                <p className="text-xs font-semibold text-foreground truncate max-w-[220px]">
                  {activeApprovalAlert.title}
                </p>
              </div>
            </div>

            <button
              onClick={dismissActiveApproval}
              className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-md"
              aria-label="Dismiss approval alert"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="py-2.5 space-y-3">
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Your workflow execution paused at human authorization gate for operation:{" "}
              <code className="px-1 py-0.5 rounded bg-muted font-mono font-semibold text-foreground">
                {activeApprovalAlert.operation}
              </code>
            </p>

            <div className="flex items-center gap-2 pt-1">
              <Button
                variant="outline"
                size="sm"
                className="flex-1 h-8 text-xs"
                onClick={dismissActiveApproval}
              >
                Dismiss
              </Button>
              <Button
                size="sm"
                className="flex-1 h-8 text-xs bg-amber-600 hover:bg-amber-700 text-white"
                onClick={() => {
                  dismissActiveApproval();
                  router.push(`/approvals?run_id=${activeApprovalAlert.runId}`);
                }}
              >
                <span>Open Approval</span>
                <ArrowRight className="h-3.5 w-3.5 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
