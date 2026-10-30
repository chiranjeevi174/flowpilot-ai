"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Calendar,
  Clock,
  Play,
  Pause,
  Trash2,
  Plus,
  RefreshCw,
  Sparkles,
  History,
  CheckCircle2,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { ScheduledWorkflow, ScheduleType } from "@/types";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { formatDate } from "@/lib/utils";

const COMMON_TIMEZONES = [
  { value: "UTC", label: "UTC (Coordinated Universal Time)" },
  { value: "America/New_York", label: "America/New York (Eastern Time)" },
  { value: "America/Chicago", label: "America/Chicago (Central Time)" },
  { value: "America/Denver", label: "America/Denver (Mountain Time)" },
  { value: "America/Los_Angeles", label: "America/Los Angeles (Pacific Time)" },
  { value: "Europe/London", label: "Europe/London (GMT/BST)" },
  { value: "Europe/Paris", label: "Europe/Paris (CET/CEST)" },
  { value: "Europe/Berlin", label: "Europe/Berlin (CET/CEST)" },
  { value: "Asia/Dubai", label: "Asia/Dubai (GST)" },
  { value: "Asia/Kolkata", label: "Asia/Kolkata (IST)" },
  { value: "Asia/Singapore", label: "Asia/Singapore (SGT)" },
  { value: "Asia/Tokyo", label: "Asia/Tokyo (JST)" },
  { value: "Australia/Sydney", label: "Australia/Sydney (AEST/AEDT)" },
];

const DAYS_OF_WEEK = [
  { label: "Mon", value: 0 },
  { label: "Tue", value: 1 },
  { label: "Wed", value: 2 },
  { label: "Thu", value: 3 },
  { label: "Fri", value: 4 },
  { label: "Sat", value: 5 },
  { label: "Sun", value: 6 },
];

export default function SchedulesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState<"active" | "history">("active");
  const [isCreateOpen, setIsCreateOpen] = React.useState(false);
  const [deleteTarget, setDeleteTarget] = React.useState<ScheduledWorkflow | null>(null);

  // Form states
  const [name, setName] = React.useState("");
  const [workflowRequest, setWorkflowRequest] = React.useState("");
  const [scheduleType, setScheduleType] = React.useState<ScheduleType>("daily");
  const [timezone, setTimezone] = React.useState("UTC");
  const [dailyTime, setDailyTime] = React.useState("09:00");
  const [selectedDays, setSelectedDays] = React.useState<number[]>([0, 1, 2, 3, 4]); // Mon-Fri
  const [oneTimeDatetime, setOneTimeDatetime] = React.useState("");

  const {
    data: schedules = [],
    isLoading,
    isRefetching,
    refetch,
  } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => api.schedules.listSchedules(),
  });

  // Distinct lifecycle separation:
  // Active Schedules:
  // - Upcoming one-time schedules (where last_run_at is null)
  // - All recurring schedules (whether currently active or paused)
  const activeSchedules = schedules.filter((s) => {
    if (s.schedule_type === "one_time") {
      return !s.last_run_at;
    }
    return true;
  });

  // Count of genuinely active (enabled) schedules matching backend metric definition
  const activeCount = schedules.filter((s) => {
    if (s.schedule_type === "one_time") {
      return !s.last_run_at && s.is_active;
    }
    return s.is_active;
  }).length;

  // Schedule History:
  // - Completed/triggered one-time schedules (where last_run_at is not null)
  const historySchedules = schedules.filter((s) => {
    if (s.schedule_type === "one_time") {
      return !!s.last_run_at;
    }
    return false;
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      let config: Record<string, any> = {};
      if (scheduleType === "daily") {
        config = { time: dailyTime };
      } else if (scheduleType === "weekly") {
        if (selectedDays.length === 0) {
          throw new Error("Please select at least one day of the week.");
        }
        config = { time: dailyTime, days_of_week: selectedDays };
      } else if (scheduleType === "one_time") {
        if (!oneTimeDatetime) {
          throw new Error("Please select target execution date and time.");
        }
        const dt = new Date(oneTimeDatetime);
        config = { run_at: dt.toISOString() };
      }

      return api.schedules.createSchedule({
        name: name.trim(),
        workflow_request: workflowRequest.trim(),
        schedule_type: scheduleType,
        timezone,
        schedule_configuration: config,
      });
    },
    onSuccess: (data) => {
      toast.success("Schedule created successfully", {
        description: `"${data.name}" will run according to its recurrence rule.`,
      });
      setIsCreateOpen(false);
      resetForm();
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
    },
    onError: (err: any) => {
      toast.error("Failed to create schedule", {
        description: err.message || "An error occurred during creation.",
      });
    },
  });

  const pauseMutation = useMutation({
    mutationFn: (id: string) => api.schedules.pauseSchedule(id),
    onSuccess: (data) => {
      toast.info("Schedule paused", {
        description: `"${data.name}" is now inactive.`,
      });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: (id: string) => api.schedules.resumeSchedule(id),
    onSuccess: (data) => {
      toast.success("Schedule resumed", {
        description: `"${data.name}" is active again.`,
      });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.schedules.deleteSchedule(id),
    onSuccess: () => {
      toast.success("Schedule record removed");
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
    },
  });

  const triggerNowMutation = useMutation({
    mutationFn: (schedule: ScheduledWorkflow) =>
      api.workflows.createRun({ request: schedule.workflow_request }),
    onSuccess: (run) => {
      toast.success("Workflow execution launched!", {
        description: "Redirecting to execution monitor...",
      });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      router.push(`/executions/${run.id}`);
    },
  });

  const resetForm = () => {
    setName("");
    setWorkflowRequest("");
    setScheduleType("daily");
    setTimezone("UTC");
    setDailyTime("09:00");
    setSelectedDays([0, 1, 2, 3, 4]);
    setOneTimeDatetime("");
  };

  const toggleDay = (day: number) => {
    if (selectedDays.includes(day)) {
      setSelectedDays(selectedDays.filter((d) => d !== day));
    } else {
      setSelectedDays([...selectedDays, day].sort());
    }
  };

  const formatConfigSummary = (schedule: ScheduledWorkflow) => {
    const cfg = schedule.schedule_configuration || {};
    if (schedule.schedule_type === "daily") {
      return `Daily at ${cfg.time || "00:00"} ${schedule.timezone}`;
    }
    if (schedule.schedule_type === "weekly") {
      const days = (cfg.days_of_week || [])
        .map((d: number) => DAYS_OF_WEEK.find((item) => item.value === d)?.label)
        .filter(Boolean)
        .join(", ");
      return `Weekly on [${days || "all days"}] at ${cfg.time || "00:00"} ${schedule.timezone}`;
    }
    if (schedule.schedule_type === "one_time") {
      return `One-time on ${cfg.run_at ? formatDate(cfg.run_at) : "scheduled time"}`;
    }
    return schedule.schedule_type;
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow Schedules"
        description="Configure automated recurring background workflows, recurring business automations, and one-time tasks."
      >
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isRefetching}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${isRefetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setIsCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            New Schedule
          </Button>
        </div>
      </PageHeader>

      {/* Tabs: Active Schedules vs Schedule History */}
      <div className="flex items-center gap-2 border-b border-border">
        <button
          onClick={() => setActiveTab("active")}
          className={`flex items-center gap-2 pb-3 px-1 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
            activeTab === "active"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <Calendar className="h-4 w-4" />
          Active Schedules
          <Badge variant="outline" className="ml-1 text-[10px] font-mono">
            {activeCount}
          </Badge>
        </button>
        <button
          onClick={() => setActiveTab("history")}
          className={`flex items-center gap-2 pb-3 px-1 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
            activeTab === "history"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <History className="h-4 w-4" />
          Schedule History
          <Badge variant="outline" className="ml-1 text-[10px] font-mono">
            {historySchedules.length}
          </Badge>
        </button>
      </div>

      {/* Content based on Active Tab */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-56 w-full rounded-xl" />
          ))}
        </div>
      ) : activeTab === "active" ? (
        activeSchedules.length === 0 ? (
          <EmptyState
            icon={<Calendar className="h-8 w-8 text-primary" />}
            title="No active scheduled workflows"
            description="Create your first automated schedule to execute multi-agent workflows periodically without manual intervention."
            action={
              <Button size="sm" onClick={() => setIsCreateOpen(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Create First Schedule
              </Button>
            }
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {activeSchedules.map((schedule) => (
              <Card
                key={schedule.id}
                className={`flex flex-col justify-between border-border shadow-xs hover:border-primary/40 transition-all min-w-0 ${
                  !schedule.is_active ? "opacity-75 bg-muted/20" : ""
                }`}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-2 min-w-0">
                    <div className="min-w-0 flex-1">
                      <CardTitle className="text-sm font-semibold truncate text-foreground" title={schedule.name}>
                        {schedule.name}
                      </CardTitle>
                      <div className="flex items-center gap-2 mt-1.5">
                        <Badge
                          variant={schedule.is_active ? "success" : "secondary"}
                          className="text-[10px]"
                        >
                          {schedule.is_active ? "Active" : "Paused"}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] capitalize font-mono">
                          {schedule.schedule_type.replace("_", "-")}
                        </Badge>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {schedule.is_active ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-[#B7791F] hover:bg-[#B7791F]/10"
                          title="Pause Schedule"
                          onClick={() => pauseMutation.mutate(schedule.id)}
                          disabled={pauseMutation.isPending}
                        >
                          <Pause className="h-3.5 w-3.5" />
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-[#16866B] hover:bg-[#16866B]/10"
                          title="Resume Schedule"
                          onClick={() => resumeMutation.mutate(schedule.id)}
                          disabled={resumeMutation.isPending}
                        >
                          <Play className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                        title="Delete Schedule"
                        onClick={() => setDeleteTarget(schedule)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 pb-3 text-xs flex-1 min-w-0">
                  <p
                    className="text-muted-foreground line-clamp-2 bg-muted/30 p-2.5 rounded-lg border border-border text-xs cursor-help"
                    title={schedule.workflow_request}
                  >
                    &ldquo;{schedule.workflow_request}&rdquo;
                  </p>

                  <div className="space-y-1.5 pt-1 text-muted-foreground">
                    <div className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5 text-primary shrink-0" />
                      <span className="font-medium text-foreground text-xs truncate">
                        {formatConfigSummary(schedule)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between pt-1 border-t border-border/60 text-[11px]">
                      <span>Next execution:</span>
                      <span className="font-mono text-foreground font-medium">
                        {schedule.next_run_at ? formatDate(schedule.next_run_at) : "None"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[11px]">
                      <span>Last run:</span>
                      <span className="font-mono text-foreground">
                        {schedule.last_run_at ? formatDate(schedule.last_run_at) : "Never"}
                      </span>
                    </div>
                  </div>
                </CardContent>

                <CardFooter className="pt-2.5 pb-2.5 border-t border-border bg-card flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground font-mono">
                    TZ: {schedule.timezone}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs h-7 px-2.5 hover:border-primary hover:text-primary"
                    onClick={() => triggerNowMutation.mutate(schedule)}
                    disabled={triggerNowMutation.isPending}
                  >
                    <Sparkles className="h-3 w-3 mr-1 text-[#087F72]" />
                    Run Now
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        )
      ) : (
        /* Schedule History Tab */
        historySchedules.length === 0 ? (
          <EmptyState
            icon={<History className="h-8 w-8 text-primary" />}
            title="No schedule history yet"
            description="Completed and triggered one-time workflows will automatically archive here once their executions are dispatched."
          />
        ) : (
          <div className="rounded-xl border border-border bg-card shadow-xs overflow-hidden">
            <div className="px-4 py-3 border-b border-border bg-muted/20 flex items-center justify-between">
              <div>
                <h3 className="text-xs font-semibold text-foreground">Archived One-Time Schedules</h3>
                <p className="text-[11px] text-muted-foreground">
                  Historical record of fulfilled one-time schedules with linked execution details.
                </p>
              </div>
              <Badge variant="outline" className="text-xs font-mono">
                {historySchedules.length} Executed
              </Badge>
            </div>

            <div className="overflow-x-auto">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>
                    <TableHead className="text-xs font-semibold">Schedule Name</TableHead>
                    <TableHead className="text-xs font-semibold">Cadence</TableHead>
                    <TableHead className="text-xs font-semibold">Configured Execution</TableHead>
                    <TableHead className="text-xs font-semibold">Triggered At</TableHead>
                    <TableHead className="text-xs font-semibold">Schedule State</TableHead>
                    <TableHead className="text-xs font-semibold">Execution</TableHead>
                    <TableHead className="text-xs font-semibold text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {historySchedules.map((schedule) => (
                    <TableRow key={schedule.id} className="hover:bg-muted/20">
                      <TableCell className="font-medium text-xs">
                        <span className="block font-semibold text-foreground truncate max-w-[200px]" title={schedule.name}>
                          {schedule.name}
                        </span>
                        <span className="text-[11px] text-muted-foreground line-clamp-1 truncate max-w-[200px]" title={schedule.workflow_request}>
                          {schedule.workflow_request}
                        </span>
                      </TableCell>

                      <TableCell>
                        <Badge variant="outline" className="text-[10px] uppercase font-mono">
                          One-Time
                        </Badge>
                      </TableCell>

                      <TableCell className="text-xs font-mono text-muted-foreground">
                        {schedule.schedule_configuration?.run_at
                          ? formatDate(schedule.schedule_configuration.run_at)
                          : formatDate(schedule.next_run_at || schedule.created_at)}
                        <span className="block text-[10px] text-muted-foreground/80 font-sans">
                          TZ: {schedule.timezone}
                        </span>
                      </TableCell>

                      <TableCell className="text-xs font-mono text-foreground font-medium">
                        {schedule.last_run_at ? formatDate(schedule.last_run_at) : "Triggered"}
                      </TableCell>

                      <TableCell>
                        <Badge variant="success" className="text-[10px] inline-flex items-center gap-1 font-semibold">
                          <CheckCircle2 className="h-3 w-3" />
                          Completed
                        </Badge>
                      </TableCell>

                      <TableCell className="text-xs">
                        {schedule.latest_run_id ? (
                          <div className="space-y-1">
                            <Link
                              href={`/executions/${schedule.latest_run_id}`}
                              className="inline-flex items-center gap-1 text-[11px] font-mono font-medium text-primary hover:underline"
                            >
                              <span>{schedule.latest_run_id.slice(0, 8)}...</span>
                              <ExternalLink className="h-2.5 w-2.5" />
                            </Link>
                            {schedule.latest_run_status && (
                              <div>
                                <StatusBadge status={schedule.latest_run_status as any} />
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground text-xs italic">Dispatched</span>
                        )}
                      </TableCell>

                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {schedule.latest_run_id && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs px-2.5 hover:border-primary hover:text-primary"
                              onClick={() => router.push(`/executions/${schedule.latest_run_id}`)}
                            >
                              <ExternalLink className="h-3 w-3 mr-1" />
                              View Run
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                            title="Delete Schedule Record"
                            onClick={() => setDeleteTarget(schedule)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )
      )}

      {/* Create Modal */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Calendar className="h-5 w-5 text-primary" />
              Create Scheduled Workflow
            </DialogTitle>
            <DialogDescription>
              Set up automated background executions on a daily, weekly, or one-time basis.
            </DialogDescription>
          </DialogHeader>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
            className="space-y-4 py-2"
          >
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground">
                Schedule Name <span className="text-rose-500">*</span>
              </label>
              <Input
                placeholder="e.g. Daily Operations Summary"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground">
                Natural Language Workflow Request <span className="text-rose-500">*</span>
              </label>
              <Textarea
                placeholder="e.g. Fetch active user count from database, summarize key activity, and post an alert to Slack #general."
                value={workflowRequest}
                onChange={(e) => setWorkflowRequest(e.target.value)}
                required
                className="min-h-[85px] text-xs"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Recurrence Type</label>
                <select
                  value={scheduleType}
                  onChange={(e) => setScheduleType(e.target.value as ScheduleType)}
                  className="w-full text-xs rounded-md border border-input bg-background px-3 py-2 text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="one_time">One-Time</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Timezone (IANA)</label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full text-xs rounded-md border border-input bg-background px-3 py-2 text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  {COMMON_TIMEZONES.map((tz) => (
                    <option key={tz.value} value={tz.value}>
                      {tz.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Recurrence Specific Inputs */}
            {scheduleType === "daily" && (
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Run Time (HH:MM)</label>
                <Input
                  type="time"
                  value={dailyTime}
                  onChange={(e) => setDailyTime(e.target.value)}
                  required
                />
              </div>
            )}

            {scheduleType === "weekly" && (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">Run Time (HH:MM)</label>
                  <Input
                    type="time"
                    value={dailyTime}
                    onChange={(e) => setDailyTime(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">Days of the Week</label>
                  <div className="flex items-center gap-1.5">
                    {DAYS_OF_WEEK.map((day) => {
                      const isSelected = selectedDays.includes(day.value);
                      return (
                        <button
                          key={day.value}
                          type="button"
                          onClick={() => toggleDay(day.value)}
                          className={`flex-1 py-1.5 text-xs font-medium rounded-md border transition-all cursor-pointer ${
                            isSelected
                              ? "bg-primary text-primary-foreground border-primary"
                              : "bg-muted/50 text-muted-foreground border-border hover:bg-muted"
                          }`}
                        >
                          {day.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {scheduleType === "one_time" && (
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Target Date & Time</label>
                <Input
                  type="datetime-local"
                  value={oneTimeDatetime}
                  onChange={(e) => setOneTimeDatetime(e.target.value)}
                  required
                />
              </div>
            )}

            <DialogFooter className="pt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setIsCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={createMutation.isPending || !name.trim() || !workflowRequest.trim()}
              >
                {createMutation.isPending ? (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                    Creating...
                  </>
                ) : (
                  "Create Schedule"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-rose-600">
              <Trash2 className="h-5 w-5" />
              Delete Scheduled Workflow
            </DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the schedule &ldquo;{deleteTarget?.name}&rdquo;?
              This action will remove the scheduling definition. Historical execution records remain preserved.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeleteTarget(null)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete Schedule"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
