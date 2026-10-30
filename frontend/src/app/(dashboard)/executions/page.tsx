"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Filter, ListTree, RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api/client";
import { formatDate } from "@/lib/utils";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function ExecutionsPage() {
  const router = useRouter();
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [page, setPage] = useState<number>(0);
  const limit = 10;

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["workflows", "list", statusFilter, page],
    queryFn: () =>
      api.workflows.listRuns({
        status: statusFilter || undefined,
        limit,
        offset: page * limit,
      }),
    refetchInterval: 10000,
  });

  const filteredItems = (data?.items || []).filter((run) => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      run.original_request.toLowerCase().includes(query) ||
      run.id.toLowerCase().includes(query) ||
      run.detected_intent?.intent?.toLowerCase().includes(query)
    );
  });

  const totalPages = Math.ceil((data?.total || 0) / limit);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow Executions"
        description="Comprehensive audit trail and telemetry for all multi-agent executions"
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          className="text-xs"
        >
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
        <Link href="/workflows">
          <Button size="sm" className="text-xs">
            New Workflow
          </Button>
        </Link>
      </PageHeader>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="relative w-full sm:w-80">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search request or ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 h-9 text-xs"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Filter className="h-4 w-4 text-muted-foreground shrink-0" />
          <Select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(0);
            }}
            className="h-9 text-xs w-full sm:w-48"
          >
            <option value="">All Statuses</option>
            <option value="running">Running</option>
            <option value="awaiting_approval">Awaiting Approval</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </Select>
        </div>
      </div>

      {/* Executions Table */}
      <Card className="overflow-hidden border-border shadow-xs">
        {isLoading ? (
          <div className="p-6 space-y-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="py-12">
            <EmptyState
              icon={<ListTree className="h-8 w-8 text-muted-foreground" />}
              title="No workflow executions found"
              description={
                statusFilter
                  ? `No executions match the status filter '${statusFilter}'.`
                  : "You have not executed any workflows yet."
              }
              actionLabel="Launch Workflow"
              onAction={() => router.push("/workflows")}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[140px]">Status</TableHead>
                  <TableHead>Workflow Request</TableHead>
                  <TableHead className="w-[140px]">Intent</TableHead>
                  <TableHead className="w-[160px]">Created At</TableHead>
                  <TableHead className="w-[160px]">Completed At</TableHead>
                  <TableHead className="text-right w-[100px]">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredItems.map((run) => (
                  <TableRow key={run.id} className="hover:bg-muted/40">
                    <TableCell>
                      <StatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="max-w-[320px] min-w-[200px]">
                      <p
                        className="text-xs font-medium text-foreground truncate cursor-help"
                        title={run.original_request}
                      >
                        {run.original_request}
                      </p>
                      <span className="text-[11px] text-muted-foreground font-mono">
                        ID: {run.id.slice(0, 8)}...
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-muted text-foreground/80 border border-border">
                        {run.detected_intent?.intent || "General"}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(run.created_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {run.completed_at ? formatDate(run.completed_at) : "In Progress"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Link href={`/executions/${run.id}`}>
                        <Button variant="ghost" size="sm" className="h-7 px-2.5 text-xs text-primary hover:text-primary hover:bg-primary/10">
                          Details <ArrowRight className="ml-1 h-3 w-3" />
                        </Button>
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground px-2">
          <span>
            Showing page {page + 1} of {totalPages} ({data?.total} total runs)
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
              className="h-8 text-xs"
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages - 1}
              onClick={() => setPage(page + 1)}
              className="h-8 text-xs"
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
