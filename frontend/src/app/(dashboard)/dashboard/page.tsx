"use client";

import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Cpu,
  Layers,
  Plus,
  Zap,
  Mail,
  MessageSquare,
  FileSpreadsheet,
} from "lucide-react";
import { api } from "@/lib/api/client";
import { formatDate, formatCurrency } from "@/lib/utils";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function DashboardPage() {
  // Query 1: Operational Health and System Counters
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["monitoring", "health"],
    queryFn: () => api.monitoring.getHealth(),
    refetchInterval: 10000,
  });

  // Query 2: Recent Workflow Executions
  const { data: recentRuns, isLoading: runsLoading } = useQuery({
    queryKey: ["workflows", "recent"],
    queryFn: () => api.workflows.listRuns({ limit: 5 }),
    refetchInterval: 10000,
  });

  // Query 3: Active Connections
  const { data: connections, isLoading: connectionsLoading } = useQuery({
    queryKey: ["integrations", "connections"],
    queryFn: () => api.integrations.listConnections(),
  });

  // Query 4: LLM Usage
  const { data: usageRecords } = useQuery({
    queryKey: ["llm", "usage"],
    queryFn: () => api.llm.getUsageHistory(20),
  });

  const runsByStatus = health?.runs_by_status || {};
  const runningCount = runsByStatus["running"] || 0;
  const completedCount = runsByStatus["completed"] || 0;
  const failedCount = runsByStatus["failed"] || 0;
  const awaitingCount = runsByStatus["awaiting_approval"] || 0;
  const totalRuns = health?.total_runs ?? 0;
  const successRate = totalRuns > 0 ? Math.round((completedCount / totalRuns) * 100) : 100;

  // Compute total tokens and costs from usage records
  const totalTokens = (usageRecords || []).reduce((acc, curr) => acc + (curr.total_tokens || 0), 0);
  const totalCost = (usageRecords || []).reduce(
    (acc, curr) => acc + (curr.estimated_cost ? Number(curr.estimated_cost) : 0),
    0
  );

  return (
    <div className="space-y-6 min-w-0">
      {/* Page Header with Primary Action */}
      <PageHeader
        title="Operations Command Center"
        description="Real-time multi-agent workflow telemetry, human approval gates, and multi-channel dispatch metrics"
      >
        <Link href="/workflows">
          <Button size="sm" className="shadow-xs">
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New Workflow
          </Button>
        </Link>
      </PageHeader>

      {/* Primary Telemetry Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Executions */}
        <Card className="hover:border-primary/40 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-1.5 p-4">
            <CardTitle className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">
              Total Executions
            </CardTitle>
            <div className="p-1.5 rounded-md bg-primary/10 text-primary">
              <Activity className="h-3.5 w-3.5" />
            </div>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            {healthLoading ? (
              <Skeleton className="h-8 w-24 my-1" />
            ) : (
              <div className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
                {totalRuns}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground mt-1 truncate">
              Across all compiled agent graphs
            </p>
          </CardContent>
        </Card>

        {/* Active Executions */}
        <Card className="hover:border-primary/40 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-1.5 p-4">
            <CardTitle className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">
              Active Executions
            </CardTitle>
            <div className="p-1.5 rounded-md bg-[#B7791F]/10 text-[#B7791F] dark:text-[#FBBF24]">
              <Zap className="h-3.5 w-3.5" />
            </div>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            {healthLoading ? (
              <Skeleton className="h-8 w-16 my-1" />
            ) : (
              <div className="text-2xl md:text-3xl font-bold tracking-tight text-[#B7791F] dark:text-[#FBBF24] flex items-center gap-2">
                {runningCount}
                {runningCount > 0 && (
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#B7791F] opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-[#B7791F]" />
                  </span>
                )}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground mt-1 truncate">
              Orchestrating in Celery worker
            </p>
          </CardContent>
        </Card>

        {/* Pending Approvals */}
        <Card className="hover:border-[#B7791F]/50 transition-colors border-[#B7791F]/30 bg-[#B7791F]/5">
          <CardHeader className="flex flex-row items-center justify-between pb-1.5 p-4">
            <CardTitle className="text-[11px] font-semibold uppercase text-[#B7791F] dark:text-[#FBBF24] tracking-wider">
              Pending Approvals
            </CardTitle>
            <div className="p-1.5 rounded-md bg-[#B7791F]/15 text-[#B7791F] dark:text-[#FBBF24]">
              <AlertTriangle className="h-3.5 w-3.5" />
            </div>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            {healthLoading ? (
              <Skeleton className="h-8 w-16 my-1" />
            ) : (
              <div className="text-2xl md:text-3xl font-bold tracking-tight text-[#B7791F] dark:text-[#FBBF24]">
                {awaitingCount}
              </div>
            )}
            <div className="flex items-center justify-between mt-1 text-[11px]">
              <span className="text-muted-foreground">Sensitive operations</span>
              {awaitingCount > 0 && (
                <Link
                  href="/approvals"
                  className="font-medium text-[#B7791F] dark:text-[#FBBF24] hover:underline flex items-center shrink-0"
                >
                  Review <ArrowRight className="ml-1 h-3 w-3" />
                </Link>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Active Schedules */}
        <Card className="hover:border-primary/40 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-1.5 p-4">
            <CardTitle className="text-[11px] font-semibold uppercase text-muted-foreground tracking-wider">
              Active Schedules
            </CardTitle>
            <div className="p-1.5 rounded-md bg-purple-500/10 text-purple-600 dark:text-purple-400">
              <CalendarClock className="h-3.5 w-3.5" />
            </div>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            {healthLoading ? (
              <Skeleton className="h-8 w-16 my-1" />
            ) : (
              <div className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
                {health?.active_schedules ?? 0}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground mt-1 truncate">
              Periodic automated runners
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Secondary Operational Panels (Properly Structured - Zero Overflow) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 min-w-0">
        {/* Completed vs Failed Rate */}
        <Card className="p-4 flex flex-col justify-between space-y-3 min-w-0">
          <div className="flex items-center justify-between gap-2 min-w-0">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#16866B]/10 text-[#16866B] dark:text-[#2DD4BF] shrink-0">
                <CheckCircle2 className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <span className="text-xs font-semibold text-foreground block truncate">
                  Execution Success
                </span>
                <span className="text-[11px] text-muted-foreground block truncate">
                  {completedCount} succeeded / {failedCount} failed
                </span>
              </div>
            </div>
            <Badge variant="success" className="text-[11px] font-semibold shrink-0">
              {successRate}% Rate
            </Badge>
          </div>
          <div className="w-full bg-muted/60 h-1.5 rounded-full overflow-hidden">
            <div
              className="bg-[#16866B] h-full rounded-full transition-all duration-500"
              style={{ width: `${Math.min(Math.max(successRate, 0), 100)}%` }}
            />
          </div>
        </Card>

        {/* LLM Usage & Estimated Cost */}
        <Card className="p-4 flex flex-col justify-between space-y-3 min-w-0">
          <div className="flex items-center justify-between gap-2 min-w-0">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#087F72]/10 text-[#087F72] dark:text-[#2DD4BF] shrink-0">
                <Cpu className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <span className="text-xs font-semibold text-foreground block truncate">
                  LLM Token Usage
                </span>
                <span className="text-[11px] text-muted-foreground block truncate">
                  Est. cost: {formatCurrency(totalCost)}
                </span>
              </div>
            </div>
            <Link href="/settings/llm" className="shrink-0">
              <Button variant="ghost" size="xs" className="text-[11px] h-7 px-2">
                Configure
              </Button>
            </Link>
          </div>
          <div className="flex items-center justify-between text-[11px] pt-1 border-t border-border/50 text-muted-foreground">
            <span>Tokens Orchestrated</span>
            <span className="font-mono font-medium text-foreground">
              {totalTokens.toLocaleString()}
            </span>
          </div>
        </Card>

        {/* Infrastructure & Outbox Status */}
        <Card className="p-4 flex flex-col justify-between space-y-3 min-w-0">
          <div className="flex items-center justify-between gap-2 min-w-0">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 shrink-0">
                <Layers className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <span className="text-xs font-semibold text-foreground block truncate">
                  System Infrastructure
                </span>
                <span className="text-[11px] text-muted-foreground block truncate">
                  Queue: {health?.celery_queue_depth ?? 0} | Outbox fail: {health?.failed_outbox_count ?? 0}
                </span>
              </div>
            </div>
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#16866B]/10 text-[#16866B] dark:text-[#2DD4BF] border border-[#16866B]/20 shrink-0">
              <span className="h-1.5 w-1.5 rounded-full bg-[#16866B] animate-pulse" />
              Live
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] pt-1 border-t border-border/50 text-muted-foreground">
            <span>PostgreSQL &amp; Redis</span>
            <span className="font-medium text-foreground">
              {health?.database_connected && health?.redis_connected ? "Operational" : "Degraded"}
            </span>
          </div>
        </Card>
      </div>

      {/* Main Operational Section: Recent Runs & Connected Integrations */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 min-w-0">
        {/* Left Column (2 spans): Recent Executions Table */}
        <div className="lg:col-span-2 space-y-3 min-w-0">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-foreground">Recent Workflow Runs</h2>
              <p className="text-xs text-muted-foreground">Latest multi-agent executions and streaming status</p>
            </div>
            <Link href="/executions">
              <Button variant="outline" size="xs" className="h-7 text-xs">
                View All <ArrowRight className="ml-1 h-3 w-3" />
              </Button>
            </Link>
          </div>

          <Card className="overflow-hidden">
            {runsLoading ? (
              <div className="p-5 space-y-3">
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
              </div>
            ) : !recentRuns?.items || recentRuns.items.length === 0 ? (
              <div className="p-8 text-center text-xs text-muted-foreground">
                No workflow runs recorded yet. Start by creating your first workflow!
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status</TableHead>
                    <TableHead>Workflow Request</TableHead>
                    <TableHead>Intent</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recentRuns.items.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell className="whitespace-nowrap">
                        <StatusBadge status={run.status} />
                      </TableCell>
                      <TableCell className="max-w-[260px] min-w-[160px]">
                        <p className="text-xs font-medium text-foreground truncate" title={run.original_request}>
                          {run.original_request}
                        </p>
                        <span className="text-[10px] text-muted-foreground font-mono">
                          ID: {run.id.slice(0, 8)}...
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground">
                          {run.detected_intent?.intent || "General"}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatDate(run.created_at)}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        <Link href={`/executions/${run.id}`}>
                          <Button variant="ghost" size="xs" className="h-7 px-2.5 text-[11px]">
                            Monitor
                          </Button>
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>
        </div>

        {/* Right Column: Connected Applications */}
        <div className="space-y-3 min-w-0">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-foreground">Connected Integrations</h2>
              <p className="text-xs text-muted-foreground">Authorized external dispatch platforms</p>
            </div>
            <Link href="/integrations">
              <Button variant="outline" size="xs" className="h-7 text-xs">
                Manage
              </Button>
            </Link>
          </div>

          <Card className="p-4 space-y-3">
            {connectionsLoading ? (
              <div className="space-y-2.5">
                <Skeleton className="h-12 w-full rounded-md" />
                <Skeleton className="h-12 w-full rounded-md" />
                <Skeleton className="h-12 w-full rounded-md" />
              </div>
            ) : (
              <div className="space-y-2.5">
                {/* Gmail Card */}
                {(() => {
                  const gmailConn = (connections || []).find((c) => c.provider === "google" && c.service === "gmail");
                  return (
                    <div className="flex items-center justify-between p-2.5 rounded-md border border-border/80 bg-muted/20">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-red-500/10 text-red-600 shrink-0">
                          <Mail className="h-4 w-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="text-xs font-semibold text-foreground block truncate">Gmail</span>
                          <p className="text-[11px] text-muted-foreground truncate max-w-[130px]">
                            {gmailConn?.external_account_id || "Not connected"}
                          </p>
                        </div>
                      </div>
                      <StatusBadge status={gmailConn ? gmailConn.status : "revoked"} className="shrink-0 text-[10px]" />
                    </div>
                  );
                })()}

                {/* Slack Card */}
                {(() => {
                  const slackConn = (connections || []).find((c) => c.provider === "slack");
                  return (
                    <div className="flex items-center justify-between p-2.5 rounded-md border border-border/80 bg-muted/20">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-amber-500/10 text-amber-600 shrink-0">
                          <MessageSquare className="h-4 w-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="text-xs font-semibold text-foreground block truncate">Slack Workspace</span>
                          <p className="text-[11px] text-muted-foreground truncate max-w-[130px]">
                            {slackConn ? (slackConn.external_account_name || slackConn.external_account_id) : "Not connected"}
                          </p>
                        </div>
                      </div>
                      <StatusBadge status={slackConn ? slackConn.status : "revoked"} className="shrink-0 text-[10px]" />
                    </div>
                  );
                })()}

                {/* Google Sheets Card */}
                {(() => {
                  const sheetsConn = (connections || []).find(
                    (c) => c.provider === "google" && (c.service === "sheets" || c.granted_scopes?.some((s) => s.includes("spreadsheets")))
                  );
                  return (
                    <div className="flex items-center justify-between p-2.5 rounded-md border border-border/80 bg-muted/20">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#16866B]/10 text-[#16866B] shrink-0">
                          <FileSpreadsheet className="h-4 w-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="text-xs font-semibold text-foreground block truncate">Google Sheets</span>
                          <p className="text-[11px] text-muted-foreground truncate max-w-[130px]">
                            {sheetsConn?.external_account_id || "Not connected"}
                          </p>
                        </div>
                      </div>
                      <StatusBadge status={sheetsConn ? sheetsConn.status : "revoked"} className="shrink-0 text-[10px]" />
                    </div>
                  );
                })()}

                {/* WhatsApp Status Card */}
                <div className="flex items-center justify-between p-2.5 rounded-md border border-border/80 bg-muted/20">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#087F72]/10 text-[#087F72] shrink-0">
                      <MessageSquare className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <span className="text-xs font-semibold text-foreground block truncate">WhatsApp Cloud API</span>
                      <p className="text-[11px] text-muted-foreground truncate max-w-[130px]">
                        Admin / Meta Platform
                      </p>
                    </div>
                  </div>
                  <Badge variant="success" className="text-[10px] shrink-0">
                    Active
                  </Badge>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
