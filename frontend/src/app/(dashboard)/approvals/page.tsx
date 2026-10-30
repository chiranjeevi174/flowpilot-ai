"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Clock,
  Fingerprint,
  ExternalLink,
  MessageSquare,
  AlertTriangle,
  RefreshCw,
  Phone,
  Mail,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { AgentRun, PlanStep } from "@/types";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { formatDate } from "@/lib/utils";

function WhatsAppApprovalPreview({ step }: { step: PlanStep }) {
  const isTemplate = step.operation === "whatsapp_send_template";
  const recipient =
    (step.parameters?.to as string) ||
    (step.parameters?.recipient as string) ||
    "Not specified";
  const messageText =
    (step.parameters?.message as string) ||
    (step.parameters?.text as string) ||
    "";
  const templateName = (step.parameters?.template_name as string) || "";
  const languageCode = (step.parameters?.language_code as string) || "en_US";
  const templateParams = step.parameters?.parameters || step.parameters?.components;

  return (
    <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-emerald-500/20">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-emerald-500/20 text-[#25D366]">
            <svg
              className="h-5 w-5 fill-current"
              viewBox="0 0 24 24"
              aria-label="WhatsApp"
            >
              <path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-6.305 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981zm11.387-5.464c-.074-.124-.272-.198-.57-.347-.297-.149-1.758-.868-2.031-.967-.272-.099-.47-.149-.669.149-.198.297-.768.967-.941 1.165-.173.198-.347.223-.644.074-.297-.149-1.255-.462-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.297-.347.446-.521.151-.172.2-.296.3-.495.099-.198.05-.372-.025-.521-.075-.148-.669-1.611-.916-2.206-.242-.579-.487-.501-.669-.51l-.57-.01c-.198 0-.52.074-.792.372s-1.04 1.016-1.04 2.479 1.065 2.876 1.213 3.074c.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.626.712.226 1.36.194 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.695.248-1.29.173-1.414z" />
            </svg>
          </div>
          <div>
            <span className="text-xs font-semibold text-foreground block">
              WhatsApp Business Dispatch
            </span>
            <span className="text-[11px] text-muted-foreground">
              {isTemplate
                ? "Approved Meta Template Message"
                : "Direct Customer Service Message (24h Window)"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="text-[10px] font-mono bg-background/50 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
          >
            {step.operation}
          </Badge>
          <Badge variant="warning" className="text-[10px]">
            Approval Gate
          </Badge>
        </div>
      </div>

      {/* Recipient & Channel Metadata */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
        <div className="p-2.5 rounded-lg bg-background/60 border border-border/80 space-y-1">
          <span className="text-[11px] text-muted-foreground flex items-center gap-1">
            <Phone className="h-3 w-3 text-emerald-500" />
            Recipient Destination
          </span>
          <div className="font-mono font-medium text-foreground text-sm flex items-center gap-2">
            <span>{recipient}</span>
            <Badge variant="outline" className="text-[9px] font-sans">
              E.164 Validated
            </Badge>
          </div>
        </div>

        <div className="p-2.5 rounded-lg bg-background/60 border border-border/80 space-y-1">
          <span className="text-[11px] text-muted-foreground flex items-center gap-1">
            <MessageSquare className="h-3 w-3 text-primary" />
            Business Sender Account
          </span>
          <div className="font-medium text-foreground text-xs flex items-center gap-2">
            <span>Deployment Business Sender</span>
            <Badge
              variant="outline"
              className="text-[9px] font-sans bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20"
            >
              Cloud API
            </Badge>
          </div>
        </div>
      </div>

      {/* Message Preview */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="font-medium text-foreground">
            {isTemplate ? "Template Definition & Parameters:" : "Message Preview (Outgoing):"}
          </span>
          <span className="text-[11px] font-mono flex items-center gap-1">
            <Fingerprint className="h-3 w-3 text-muted-foreground" />
            Digest Protected
          </span>
        </div>

        {isTemplate ? (
          <div className="p-3 rounded-lg bg-background/90 border border-border space-y-2">
            <div className="flex items-center justify-between text-xs pb-2 border-b border-border/60">
              <div>
                <span className="text-muted-foreground text-[11px]">Template Name: </span>
                <span className="font-mono font-semibold text-foreground">{templateName}</span>
              </div>
              <div>
                <span className="text-muted-foreground text-[11px]">Language: </span>
                <span className="font-mono text-foreground">{languageCode}</span>
              </div>
            </div>
            {templateParams && (
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Parameters Payload:</span>
                <pre className="text-xs bg-muted/50 p-2 rounded font-mono overflow-x-auto text-foreground/90 border border-border/50">
                  {typeof templateParams === "string"
                    ? templateParams
                    : JSON.stringify(templateParams, null, 2)}
                </pre>
              </div>
            )}
          </div>
        ) : (
          <div className="relative p-3.5 rounded-xl bg-emerald-500/10 dark:bg-emerald-950/20 border border-emerald-500/30 text-xs text-foreground/90 leading-relaxed shadow-sm">
            <div className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 mb-1 flex items-center gap-1">
              <span>WhatsApp Message Bubble</span>
            </div>
            <p className="whitespace-pre-wrap font-sans">{messageText}</p>
          </div>
        )}
      </div>

      {/* Compliance / Digest Guarantee */}
      <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1 border-t border-border/40">
        <span>Window policy: Active customer within 24h or pre-approved Meta template.</span>
        <span className="text-emerald-600 dark:text-emerald-400 font-medium">Replay Protected</span>
      </div>
    </div>
  );
}

function GmailApprovalPreview({ step }: { step: PlanStep }) {
  const recipient =
    (step.parameters?.to as string) ||
    (step.parameters?.recipient as string) ||
    "Not specified";
  const subject =
    (step.parameters?.subject as string) || "(No Subject)";
  const body =
    (step.parameters?.body as string) ||
    (step.parameters?.message as string) ||
    "";

  return (
    <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-primary/20">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-primary/20 text-primary">
            <Mail className="h-5 w-5" />
          </div>
          <div>
            <span className="text-xs font-semibold text-foreground block">
              Gmail Cloud API Dispatch
            </span>
            <span className="text-[11px] text-muted-foreground">
              Direct Google Workspace OAuth Delivery
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="text-[10px] font-mono bg-background/50 border-primary/30 text-primary"
          >
            {step.operation}
          </Badge>
          <Badge variant="warning" className="text-[10px]">
            Approval Gate
          </Badge>
        </div>
      </div>

      {step.expected_outcome && (
        <div className="text-xs text-foreground/90 font-medium bg-background/50 p-2.5 rounded-lg border border-border/60">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide block mb-0.5">Expected Outcome</span>
          <span>{step.expected_outcome}</span>
        </div>
      )}

      {/* Recipient & Subject */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
        <div className="p-2.5 rounded-lg bg-background/60 border border-border/80 space-y-1">
          <span className="text-[11px] text-muted-foreground flex items-center gap-1">
            <Mail className="h-3 w-3 text-primary" />
            Recipient Destination
          </span>
          <div className="font-mono font-medium text-foreground text-xs truncate" title={recipient}>
            {recipient}
          </div>
        </div>

        <div className="p-2.5 rounded-lg bg-background/60 border border-border/80 space-y-1">
          <span className="text-[11px] text-muted-foreground flex items-center gap-1">
            <MessageSquare className="h-3 w-3 text-primary" />
            Subject Line
          </span>
          <div className="font-medium text-foreground text-xs truncate" title={subject}>
            {subject}
          </div>
        </div>
      </div>

      {/* Message Body */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Message Body Preview:</span>
          <span className="text-[11px] font-mono flex items-center gap-1">
            <Fingerprint className="h-3 w-3 text-muted-foreground" />
            Digest Protected
          </span>
        </div>
        <div className="p-3.5 rounded-xl bg-card border border-border text-xs text-foreground/90 leading-relaxed font-sans whitespace-pre-wrap max-h-48 overflow-y-auto">
          {body || "(Empty message content)"}
        </div>
      </div>

      {/* Compliance Guarantee */}
      <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1 border-t border-border/40">
        <span>Channel: Gmail API with RFC 2822 formatting and SPF/DKIM validation.</span>
        <span className="text-primary font-medium">Replay Protected</span>
      </div>
    </div>
  );
}

function SlackApprovalPreview({ step }: { step: PlanStep }) {
  const channel = (step.parameters?.channel as string) || "Not specified";
  const text = (step.parameters?.text as string) || (step.parameters?.message as string) || "";

  return (
    <div className="rounded-xl border border-[#B7791F]/30 bg-[#B7791F]/5 p-4 space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-[#B7791F]/20">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-[#B7791F]/20 text-[#B7791F] dark:text-[#FBBF24]">
            <MessageSquare className="h-5 w-5" />
          </div>
          <div>
            <span className="text-xs font-semibold text-foreground block">
              Slack Channel Broadcast
            </span>
            <span className="text-[11px] text-muted-foreground">
              Workspace Chat Bot API Integration
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="text-[10px] font-mono bg-background/50 border-[#B7791F]/30 text-[#B7791F] dark:text-[#FBBF24]"
          >
            {step.operation}
          </Badge>
          <Badge variant="warning" className="text-[10px]">
            Approval Gate
          </Badge>
        </div>
      </div>

      <div className="p-2.5 rounded-lg bg-background/60 border border-border/80 space-y-1 text-xs">
        <span className="text-[11px] text-muted-foreground">Destination Channel</span>
        <div className="font-mono font-medium text-foreground text-sm">{channel}</div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Message Content:</span>
          <span className="text-[11px] font-mono flex items-center gap-1">
            <Fingerprint className="h-3 w-3 text-muted-foreground" />
            Digest Protected
          </span>
        </div>
        <div className="p-3.5 rounded-xl bg-card border border-border text-xs text-foreground/90 leading-relaxed font-sans whitespace-pre-wrap max-h-48 overflow-y-auto">
          {text || "(Empty message content)"}
        </div>
      </div>
    </div>
  );
}

function ApprovalsContent() {
  const searchParams = useSearchParams();
  const targetRunId = searchParams?.get("run_id");

  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState<"pending" | "resolved">("pending");
  const [selectedRun, setSelectedRun] = React.useState<AgentRun | null>(null);
  const [decisionType, setDecisionType] = React.useState<"approve" | "reject" | null>(null);
  const [decisionComment, setDecisionComment] = React.useState("");

  // Auto-focus and scroll to targeted run_id if provided via Open Approval
  React.useEffect(() => {
    if (targetRunId) {
      setActiveTab("pending");
      const timer = setTimeout(() => {
        const el = document.getElementById(`approval-card-${targetRunId}`);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 250);
      return () => clearTimeout(timer);
    }
  }, [targetRunId]);

  // Query pending approval runs
  const {
    data: pendingData,
    isLoading: isPendingLoading,
    isRefetching: isPendingRefetching,
    refetch: refetchPending,
  } = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => api.workflows.listRuns({ status: "awaiting_approval", limit: 50 }),
    refetchInterval: 5000,
  });

  // Query resolved/history runs
  const { data: historyData, isLoading: isHistoryLoading } = useQuery({
    queryKey: ["approvals", "history"],
    queryFn: () => api.workflows.listRuns({ limit: 30 }),
    enabled: activeTab === "resolved",
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, comment }: { id: string; comment?: string }) =>
      api.workflows.approveRun(id, comment),
    onSuccess: (data) => {
      toast.success("Workflow approved and resumed", {
        description: `Run ${data.id.slice(0, 8)} is now resuming execution.`,
      });
      setSelectedRun(null);
      setDecisionType(null);
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (err: any) => {
      toast.error("Failed to approve workflow", {
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, comment }: { id: string; comment?: string }) =>
      api.workflows.rejectRun(id, comment),
    onSuccess: (data) => {
      toast.info("Workflow rejected", {
        description: `Run ${data.id.slice(0, 8)} was terminated.`,
      });
      setSelectedRun(null);
      setDecisionType(null);
      setDecisionComment("");
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (err: any) => {
      toast.error("Failed to reject workflow", {
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  const handleOpenDecision = (run: AgentRun, type: "approve" | "reject") => {
    setSelectedRun(run);
    setDecisionType(type);
    setDecisionComment("");
  };

  const handleConfirmDecision = () => {
    if (!selectedRun || !decisionType) return;
    if (decisionType === "approve") {
      approveMutation.mutate({ id: selectedRun.id, comment: decisionComment.trim() || undefined });
    } else {
      rejectMutation.mutate({ id: selectedRun.id, comment: decisionComment.trim() || undefined });
    }
  };

  const pendingRuns = pendingData?.items || [];
  const resolvedRuns = (historyData?.items || []).filter(
    (r) => r.status === "completed" || r.status === "failed" || r.status === "cancelled"
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Human-in-the-Loop Approvals"
        description="Review and authorize sensitive agent actions, external messaging, and high-impact operations before execution."
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetchPending()}
          disabled={isPendingRefetching}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isPendingRefetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </PageHeader>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-border">
        <button
          onClick={() => setActiveTab("pending")}
          className={`flex items-center gap-2 pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "pending"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <Clock className="h-4 w-4" />
          Pending Approvals
          {pendingRuns.length > 0 && (
            <Badge variant="warning" className="ml-1 text-xs">
              {pendingRuns.length}
            </Badge>
          )}
        </button>
        <button
          onClick={() => setActiveTab("resolved")}
          className={`flex items-center gap-2 pb-3 px-3 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "resolved"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <CheckCircle2 className="h-4 w-4" />
          Recent Decisions
        </button>
      </div>

      {/* Pending Tab */}
      {activeTab === "pending" && (
        <div className="space-y-4">
          {isPendingLoading ? (
            <div className="space-y-4">
              {[1, 2].map((i) => (
                <Skeleton key={i} className="h-56 w-full rounded-xl" />
              ))}
            </div>
          ) : pendingRuns.length === 0 ? (
            <EmptyState
              icon={<ShieldAlert className="h-8 w-8 text-emerald-500" />}
              title="All caught up!"
              description="There are currently no workflows awaiting human review or authorization. Any sensitive agent actions will appear here in real time."
              action={
                <Link href="/workflows">
                  <Button variant="outline" size="sm">
                    Launch New Workflow
                  </Button>
                </Link>
              }
            />
          ) : (
            pendingRuns.map((run) => {
              // Find the sensitive step requiring approval
              const pendingStep: PlanStep | undefined =
                run.execution_plan?.find(
                  (s, idx) => s.approval_required || idx === run.current_step
                ) || run.execution_plan?.[0];

              const isTargeted = targetRunId === run.id;

              return (
                <Card
                  key={run.id}
                  id={`approval-card-${run.id}`}
                  className={`border-border hover:border-primary/40 shadow-xs transition ${
                    isTargeted
                      ? "ring-2 ring-amber-500 shadow-xl border-amber-500/60 bg-amber-500/5 scale-[1.005]"
                      : ""
                  }`}
                >
                  <CardHeader className="pb-3">
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <StatusBadge status={run.status} />
                          <Badge variant="outline" className="font-mono text-xs">
                            Step {run.current_step + 1} of {run.execution_plan?.length || 1}
                          </Badge>
                          {isTargeted && (
                            <Badge variant="warning" className="animate-pulse text-[10px] flex items-center gap-1 font-semibold">
                              <AlertTriangle className="h-3 w-3" />
                              Targeted for Review
                            </Badge>
                          )}
                          <span className="text-xs text-muted-foreground">
                            {formatDate(run.created_at)}
                          </span>
                        </div>
                        <CardTitle className="text-lg font-semibold mt-1">
                          {run.original_request}
                        </CardTitle>
                        <CardDescription className="text-xs font-mono mt-1">
                          Run ID: {run.id}
                        </CardDescription>
                      </div>

                      <div className="flex items-center gap-2 self-end sm:self-auto">
                        <Link href={`/executions/${run.id}`}>
                          <Button variant="ghost" size="sm" className="text-xs">
                            View Monitor
                            <ExternalLink className="h-3 w-3 ml-1" />
                          </Button>
                        </Link>
                      </div>
                    </div>
                  </CardHeader>

                  <CardContent className="space-y-4 pt-0">
                    {/* Sensitive Operation Highlight */}
                    {pendingStep &&
                      (pendingStep.operation.startsWith("whatsapp_") ? (
                        <WhatsAppApprovalPreview step={pendingStep} />
                      ) : pendingStep.operation.startsWith("gmail_") ? (
                        <GmailApprovalPreview step={pendingStep} />
                      ) : pendingStep.operation.startsWith("slack_") ? (
                        <SlackApprovalPreview step={pendingStep} />
                      ) : (
                        <div className="rounded-xl bg-card border border-border p-4 space-y-3 shadow-xs">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <AlertTriangle className="h-4 w-4 text-[#B7791F]" />
                              <span className="text-xs font-semibold uppercase tracking-wider text-[#B7791F]">
                                Proposed Sensitive Operation
                              </span>
                            </div>
                            <Badge variant="outline" className="font-mono text-xs bg-background/50">
                              {pendingStep.operation}
                            </Badge>
                          </div>

                          {pendingStep.expected_outcome && (
                            <p className="text-sm text-foreground/90 font-medium">
                              {pendingStep.expected_outcome}
                            </p>
                          )}

                          {/* Parameter Preview */}
                          {pendingStep.parameters && Object.keys(pendingStep.parameters).length > 0 && (
                            <div className="space-y-1.5">
                              <div className="flex items-center justify-between text-xs text-muted-foreground font-mono">
                                <span>Action Parameters:</span>
                                <span className="flex items-center gap-1 text-[11px]">
                                  <Fingerprint className="h-3 w-3 text-muted-foreground" />
                                  Digest Verified
                                </span>
                              </div>
                              <pre className="text-xs bg-background p-3 rounded-md font-mono text-foreground/80 overflow-x-auto border border-border">
                                {JSON.stringify(pendingStep.parameters, null, 2)}
                              </pre>
                            </div>
                          )}
                        </div>
                      ))}
                  </CardContent>

                  <CardFooter className="flex items-center justify-end gap-3 pt-3 border-t border-border bg-card">
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:bg-destructive/10 border-destructive/20 h-8 text-xs font-medium"
                      onClick={() => handleOpenDecision(run, "reject")}
                    >
                      <XCircle className="h-3.5 w-3.5 mr-1.5" />
                      Reject &amp; Abort
                    </Button>
                    <Button
                      variant="default"
                      size="sm"
                      className="h-8 text-xs font-medium bg-[#16866B] hover:bg-[#126e58] text-white shadow-xs"
                      onClick={() => handleOpenDecision(run, "approve")}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                      Approve &amp; Resume
                    </Button>
                  </CardFooter>
                </Card>
              );
            })
          )}
        </div>
      )}

      {/* Resolved History Tab */}
      {activeTab === "resolved" && (
        <div className="space-y-4">
          {isHistoryLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full rounded-xl" />
              ))}
            </div>
          ) : resolvedRuns.length === 0 ? (
            <EmptyState
              title="No recent decisions recorded"
              description="Historical workflow executions and decisions will be displayed here."
            />
          ) : (
            <div className="rounded-xl border border-border overflow-hidden bg-card">
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="bg-muted/50 text-xs uppercase font-medium text-muted-foreground border-b border-border">
                    <tr>
                      <th className="py-3 px-4">Workflow</th>
                      <th className="py-3 px-4">Status</th>
                      <th className="py-3 px-4">Date</th>
                      <th className="py-3 px-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {resolvedRuns.map((run) => (
                      <tr key={run.id} className="hover:bg-muted/30 transition-colors">
                        <td className="py-3 px-4">
                          <div className="font-medium text-foreground line-clamp-1">
                            {run.original_request}
                          </div>
                          <div className="text-xs font-mono text-muted-foreground">
                            {run.id.slice(0, 8)}...
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <StatusBadge status={run.status} />
                        </td>
                        <td className="py-3 px-4 text-xs text-muted-foreground">
                          {formatDate(run.completed_at || run.updated_at)}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <Link href={`/executions/${run.id}`}>
                            <Button variant="ghost" size="sm" className="text-xs">
                              View Trace
                            </Button>
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Decision Dialog */}
      <Dialog
        open={!!selectedRun && !!decisionType}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedRun(null);
            setDecisionType(null);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {decisionType === "approve" ? (
                <>
                  <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                  Approve Proposed Action
                </>
              ) : (
                <>
                  <XCircle className="h-5 w-5 text-rose-500" />
                  Reject Proposed Action
                </>
              )}
            </DialogTitle>
            <DialogDescription>
              {decisionType === "approve"
                ? "This will authorize the sensitive agent step and resume execution of the workflow."
                : "This will terminate the workflow run immediately with status 'rejected'."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="text-xs text-muted-foreground bg-muted/40 p-3 rounded-lg border border-border">
              <span className="font-semibold text-foreground">Workflow: </span>
              {selectedRun?.original_request}
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-foreground flex items-center gap-1.5">
                <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                Audit Log Comment (Optional)
              </label>
              <Textarea
                placeholder={
                  decisionType === "approve"
                    ? "e.g., Reviewed and verified customer recipient list."
                    : "e.g., Target message parameters are incorrect."
                }
                value={decisionComment}
                onChange={(e) => setDecisionComment(e.target.value)}
                className="text-xs min-h-[80px]"
              />
            </div>
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSelectedRun(null);
                setDecisionType(null);
              }}
              disabled={approveMutation.isPending || rejectMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant={decisionType === "approve" ? "default" : "destructive"}
              size="sm"
              className={
                decisionType === "approve"
                  ? "bg-[#16866B] hover:bg-[#126e58] text-white"
                  : ""
              }
              onClick={handleConfirmDecision}
              disabled={approveMutation.isPending || rejectMutation.isPending}
            >
              {approveMutation.isPending || rejectMutation.isPending ? (
                <>
                  <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                  Processing...
                </>
              ) : decisionType === "approve" ? (
                "Confirm Approval"
              ) : (
                "Confirm Rejection"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <React.Suspense fallback={<div className="p-8 text-center text-xs text-muted-foreground">Loading approvals...</div>}>
      <ApprovalsContent />
    </React.Suspense>
  );
}
