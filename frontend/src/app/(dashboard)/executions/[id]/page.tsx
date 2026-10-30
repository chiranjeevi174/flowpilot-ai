"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  FileCheck2,
  ListTree,
  Radio,
  StopCircle,
  Terminal,
  Activity,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { formatDate } from "@/lib/utils";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { AgentEvent } from "@/types";
import { getDeliveryStatusMeta } from "@/lib/delivery-status";

function ExecutionDetailContent() {

  const params = useParams();
  const queryClient = useQueryClient();
  const id = params.id as string;

  const [streamEvents, setStreamEvents] = useState<AgentEvent[]>([]);
  const [isCancelling, setIsCancelling] = useState(false);
  const [streamConnected, setStreamConnected] = useState(false);

  // 1. Fetch current run details
  const { data: run, isLoading, refetch: refetchRun } = useQuery({
    queryKey: ["workflows", "detail", id],
    queryFn: () => api.workflows.getRun(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed" || status === "cancelled") {
        return false;
      }
      return 3000;
    },
  });

  // 2. Fetch past historical events
  const { data: pastEvents } = useQuery({
    queryKey: ["workflows", "events", id],
    queryFn: () => api.workflows.getRunEvents(id),
  });

  // 3. Fetch external actions and delivery states for this run
  const { data: runActions = [] } = useQuery({
    queryKey: ["workflows", "actions", id],
    queryFn: () => api.integrations.listActions(50),
    select: (actions) => actions.filter((a) => a.run_id === id),
    refetchInterval: () => {
      const isTerminal =
        run?.status === "completed" || run?.status === "failed" || run?.status === "cancelled";
      return isTerminal ? false : 3000;
    },
  });

  // 4. Setup SSE streaming connection via same-origin Next.js proxy
  useEffect(() => {
    if (!id) return;
    const isTerminal =
      run?.status === "completed" || run?.status === "failed" || run?.status === "cancelled";
    if (isTerminal) return;

    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource(`/api/proxy/agents/runs/${id}/stream`);

      eventSource.onopen = () => {
        setStreamConnected(true);
      };

      eventSource.onmessage = (e) => {
        try {
          const payload = JSON.parse(e.data);
          const newEvent: AgentEvent = {
            id:
              payload.id ||
              (typeof crypto !== "undefined" && crypto.randomUUID
                ? crypto.randomUUID()
                : Math.random().toString(36).slice(2)),
            run_id: id,
            agent_name: payload.agent_name || "orchestrator",
            event_type: e.type || payload.event_type || "message",
            event_payload: payload.event_payload || payload,
            timestamp: payload.timestamp || new Date().toISOString(),
          };

          setStreamEvents((prev) => {
            if (prev.some((item) => item.id === newEvent.id)) return prev;
            return [...prev, newEvent];
          });

          // Invalidate run queries to pick up state changes
          queryClient.invalidateQueries({ queryKey: ["workflows", "detail", id] });
        } catch (err) {
          console.debug("Failed to parse SSE payload", err);
        }
      };

      eventSource.onerror = () => {
        setStreamConnected(false);
        eventSource?.close();
      };
    } catch (err) {
      console.debug("SSE subscription initialization error", err);
    }

    return () => {
      eventSource?.close();
      setStreamConnected(false);
    };
  }, [id, run?.status, queryClient]);

  const handleCancel = async () => {
    if (!confirm("Are you sure you want to cancel this workflow run?")) return;
    setIsCancelling(true);
    try {
      await api.workflows.cancelRun(id);
      toast.success("Cancellation request submitted.");
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
      await refetchRun();
    } catch (err: any) {
      toast.error(err.message || "Failed to cancel workflow.");
    } finally {
      setIsCancelling(false);
    }
  };

  // Merge events deterministically
  const allEvents = [...(pastEvents || [])];
  for (const se of streamEvents) {
    if (!allEvents.some((e) => e.id === se.id)) {
      allEvents.push(se);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-bold">Execution Not Found</h2>
        <p className="text-sm text-muted-foreground mt-2">The specified run ID does not exist or belongs to another user.</p>
        <Link href="/executions" className="mt-4 inline-block">
          <Button variant="outline">Back to Executions</Button>
        </Link>
      </div>
    );
  }

  const isTerminal = run.status === "completed" || run.status === "failed" || run.status === "cancelled";
  const isAwaitingApproval = run.status === "awaiting_approval";

  return (
    <div className="space-y-8">
      {/* Back and Page Header */}
      <div>
        <Link
          href="/executions"
          className="inline-flex items-center text-xs font-medium text-muted-foreground hover:text-foreground mb-4"
        >
          <ArrowLeft className="mr-1.5 h-3.5 w-3.5" />
          Back to Executions
        </Link>

        <PageHeader
          title={`Execution: ${run.id.slice(0, 12)}...`}
          description={`Created on ${formatDate(run.created_at)}`}
        >
          <div className="flex items-center gap-2">
            {!isTerminal && (
              <Button
                variant="destructive"
                size="sm"
                onClick={handleCancel}
                isLoading={isCancelling}
                className="text-xs"
              >
                <StopCircle className="mr-1.5 h-3.5 w-3.5" />
                Cancel Run
              </Button>
            )}
          </div>
        </PageHeader>
      </div>

      {/* Awaiting Approval Alert Banner */}
      {isAwaitingApproval && (
        <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 animate-in fade-in-0 duration-300">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/20 text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <div>
              <h4 className="font-semibold text-sm text-foreground">
                Human Approval Required
              </h4>
              <p className="text-xs text-muted-foreground">
                A sensitive external action (sending email, posting Slack message, or spreadsheet write) is paused pending review.
              </p>
            </div>
          </div>
          <Link href="/approvals">
            <Button size="sm" className="bg-amber-600 hover:bg-amber-700 text-white text-xs">
              Review & Authorize
            </Button>
          </Link>
        </div>
      )}

      {/* Top Details Card */}
      <Card>
        <CardContent className="p-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-border/60">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <StatusBadge status={run.status} />
                {streamConnected && !isTerminal && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                    <Radio className="h-3 w-3 animate-pulse" />
                    Live SSE Stream
                  </span>
                )}
              </div>
              <h2 className="text-lg font-bold text-foreground">
                {run.original_request}
              </h2>
            </div>
            <div className="text-left md:text-right text-xs text-muted-foreground space-y-1">
              <div>Thread: <span className="font-mono text-foreground">{run.thread_id}</span></div>
              <div>Current Step: <span className="font-semibold text-foreground">{run.current_step}</span></div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 text-xs">
            <div>
              <span className="text-muted-foreground block">Started</span>
              <span className="font-medium text-foreground">{formatDate(run.created_at)}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">Completed</span>
              <span className="font-medium text-foreground">
                {run.completed_at ? formatDate(run.completed_at) : "In Progress"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">Detected Intent</span>
              <span className="font-medium text-foreground">
                {run.detected_intent?.intent || "Under Analysis"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">Target Action</span>
              <span className="font-medium text-foreground">
                {run.detected_intent?.action || "Processing"}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Orchestration Breakdown Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left: Execution Plan & Steps */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <ListTree className="h-4 w-4 text-primary" />
                LangGraph Execution Plan
              </CardTitle>
              <CardDescription>
                Multi-agent sequence synthesized by the Planning Agent
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!run.execution_plan || run.execution_plan.length === 0 ? (
                <div className="text-xs text-muted-foreground py-4 text-center">
                  Synthesizing execution plan...
                </div>
              ) : (
                <div className="space-y-3">
                  {run.execution_plan.map((step, idx) => (
                    <div
                      key={step.step_id || idx}
                      className="p-3.5 rounded-lg border border-border/80 bg-muted/20 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-xs">
                            {idx + 1}
                          </span>
                          <span className="font-mono text-xs font-semibold text-foreground">
                            {step.operation}
                          </span>
                        </div>
                        {step.approval_required && (
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-600 border border-amber-500/20">
                            Approval Gate
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {step.expected_outcome}
                      </p>
                      {step.parameters && Object.keys(step.parameters).length > 0 && (
                        <div className="pt-1.5 border-t border-border/50 text-[11px] text-muted-foreground font-mono truncate">
                          Params: {JSON.stringify(step.parameters)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* External Actions & Delivery Tracking */}
          {runActions.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <Activity className="h-4 w-4 text-emerald-500" />
                    External Actions & Delivery Tracking
                  </span>
                  <Badge variant="outline" className="text-xs font-mono">
                    {runActions.length} Dispatched
                  </Badge>
                </CardTitle>
                <CardDescription>
                  Multi-channel dispatches with cryptographic audit trail and real-time delivery status
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {runActions.map((action) => {
                  const deliveryMeta = getDeliveryStatusMeta(action);

                  return (
                    <div
                      key={action.id}
                      className="p-3.5 rounded-lg border border-border/80 bg-muted/20 space-y-2.5 text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {deliveryMeta.isWhatsApp ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-[#087F72]/10 text-[#087F72] dark:text-[#2DD4BF] border-[#087F72]/20 font-mono"
                            >
                              WhatsApp
                            </Badge>
                          ) : deliveryMeta.isGmail ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-[#C44949]/10 text-[#C44949] dark:text-[#F87171] border-[#C44949]/20 font-mono"
                            >
                              Gmail
                            </Badge>
                          ) : action.operation.startsWith("slack_") ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-[#B7791F]/10 text-[#B7791F] dark:text-[#FBBF24] border-[#B7791F]/20 font-mono"
                            >
                              Slack
                            </Badge>
                          ) : action.operation.startsWith("sheets_") ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-[#16866B]/10 text-[#16866B] dark:text-[#2DD4BF] border-[#16866B]/20 font-mono"
                            >
                              Sheets
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-[10px] font-mono">
                              External
                            </Badge>
                          )}
                          <span className="font-mono font-semibold text-foreground">
                            {action.operation}
                          </span>
                        </div>
                        <Badge
                          variant={deliveryMeta.badgeVariant}
                          className="text-[10px]"
                        >
                          {deliveryMeta.badgeLabel}
                        </Badge>
                      </div>

                      {/* Details Grid */}
                      <div className="grid grid-cols-2 gap-2 text-[11px] pt-1">
                        <div>
                          <span className="text-muted-foreground block">Action ID:</span>
                          <span className="font-mono text-foreground">{action.id.slice(0, 12)}...</span>
                        </div>
                        {action.provider_action_id && (
                          <div>
                            <span className="text-muted-foreground block">
                              {deliveryMeta.isWhatsApp ? "Meta Message ID (wamid):" : "Provider Reference:"}
                            </span>
                            <span className="font-mono text-foreground truncate block" title={action.provider_action_id}>
                              {action.provider_action_id}
                            </span>
                          </div>
                        )}
                        <div>
                          <span className="text-muted-foreground block">Dispatch Result:</span>
                          <span className="font-medium text-foreground">
                            {deliveryMeta.dispatchResultText}
                          </span>
                        </div>
                        <div>
                          <span className="text-muted-foreground block">Confirmed Delivery:</span>
                          <span className="font-medium text-foreground">
                            {deliveryMeta.confirmedDeliveryText}
                          </span>
                        </div>
                        <div>
                          <span className="text-muted-foreground block">Approval Status:</span>
                          <span className="font-medium text-[#16866B] dark:text-[#2DD4BF]">
                            {action.approval_reference ? "Approved & Authorized" : "Pre-Authorized"}
                          </span>
                        </div>
                        <div>
                          <span className="text-muted-foreground block">Digest Verified:</span>
                          <span className="font-mono text-muted-foreground">
                            {action.parameter_digest.slice(0, 8)}...
                          </span>
                        </div>
                      </div>

                      {/* Informational Callout: Accepted vs Confirmed Delivery (WhatsApp sandbox only) */}
                      {deliveryMeta.showSandboxWarning && (
                        <div className="p-2.5 rounded bg-[#B7791F]/10 border border-[#B7791F]/20 text-[#B7791F] dark:text-[#FBBF24] text-[11px] space-y-1">
                          <div className="flex items-center gap-1.5 font-medium">
                            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                            <span>Accepted by Meta Gateway — Downstream Delivery Pending</span>
                          </div>
                          <p className="text-[10px] text-muted-foreground leading-relaxed">
                            Meta accepted this payload into its dispatch queue. Recipient delivery confirmation is awaiting webhook status telemetry.
                            <strong> Note:</strong> When sending from Meta&apos;s Sandbox Test Number (+1 555-172-9819), recipients must be pre-registered and OTP-verified under <em>WhatsApp &gt; API Setup &gt; To field</em> in the Meta Developer Dashboard.
                          </p>
                        </div>
                      )}

                      {/* Delivery Errors from Webhook Telemetry */}
                      {deliveryMeta.deliveryErrors && (
                        <div className="p-2.5 rounded bg-destructive/10 border border-destructive/20 text-destructive text-[11px] space-y-1">
                          <div className="flex items-center gap-1.5 font-semibold">
                            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                            <span>Meta Delivery Failure Recorded</span>
                          </div>
                          {deliveryMeta.deliveryErrors.map((err: any, idx: number) => (
                            <div key={idx} className="text-[10px] font-mono">
                              Error {err.code}: {err.title} {err.message ? `- ${err.message}` : ""} {err.error_data?.details ? `(${err.error_data.details})` : ""}
                            </div>
                          ))}
                        </div>
                      )}

                      {action.error_message && !deliveryMeta.deliveryErrors && (
                        <div className="p-2 rounded bg-destructive/10 text-destructive text-[11px] border border-destructive/20 mt-1">
                          <strong>Failure Reason:</strong> {action.error_message}
                        </div>
                      )}

                      <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1 border-t border-border/40">
                        <span>Initiated: {formatDate(action.created_at)}</span>
                        {action.completed_at && <span>Completed: {formatDate(action.completed_at)}</span>}
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          {/* Verification & Final Result */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <FileCheck2 className="h-4 w-4 text-emerald-500" />
                Final Deliverable & Verification
              </CardTitle>
              <CardDescription>
                Output verified by the Verification Agent
              </CardDescription>
            </CardHeader>
            <CardContent>
              {run.error_message ? (
                <div className="p-4 rounded-lg bg-destructive/10 text-destructive text-xs border border-destructive/20 space-y-1">
                  <div className="font-semibold flex items-center gap-1.5">
                    <AlertCircle className="h-4 w-4" /> Execution Error
                  </div>
                  <p>{run.error_message}</p>
                </div>
              ) : run.final_result ? (
                <div className="space-y-3">
                  <div className="p-4 rounded-lg bg-muted/40 border border-border text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-96">
                    {typeof run.final_result === "string"
                      ? run.final_result
                      : JSON.stringify(run.final_result, null, 2)}
                  </div>
                </div>
              ) : (
                <div className="text-xs text-muted-foreground py-6 text-center">
                  {run.status === "running" ? "Awaiting final execution output..." : "No final result generated."}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right: Live Telemetry Event Timeline */}
        <div className="space-y-6">
          <Card className="h-full flex flex-col">
            <CardHeader className="pb-3 border-b border-border/60">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-primary" />
                  Live Audit Telemetry Stream
                </CardTitle>
                <span className="text-xs text-muted-foreground font-mono">
                  {allEvents.length} events
                </span>
              </div>
            </CardHeader>
            <CardContent className="flex-1 p-4 overflow-y-auto max-h-[600px] space-y-3">
              {allEvents.length === 0 ? (
                <div className="text-xs text-muted-foreground py-12 text-center">
                  Connecting to live event stream...
                </div>
              ) : (
                allEvents.map((event, idx) => (
                  <div
                    key={event.id || idx}
                    className="p-3 rounded-lg border border-border/70 bg-card/60 text-xs space-y-1 hover:border-border transition-colors font-mono"
                  >
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                      <span className="font-semibold text-primary">[{event.agent_name}]</span>
                      <span>{formatDate(event.timestamp)}</span>
                    </div>
                    <div className="font-bold text-foreground">
                      {event.event_type}
                    </div>
                    {event.event_payload && (
                      <pre className="text-[11px] text-muted-foreground/90 whitespace-pre-wrap overflow-x-auto pt-1 border-t border-border/40">
                        {JSON.stringify(event.event_payload, null, 2)}
                      </pre>
                    )}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function ExecutionDetailPage() {
  return (
    <React.Suspense
      fallback={
        <div className="space-y-6">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-64 w-full" />
        </div>
      }
    >
      <ExecutionDetailContent />
    </React.Suspense>
  );
}
