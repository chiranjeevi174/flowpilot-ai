"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
  useMemo,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import type { AppNotification, ScheduledWorkflow, AgentRun } from "@/types";

export interface ActiveCountdown {
  scheduleId: string;
  scheduleName: string;
  targetTimestamp: number;
  remainingSeconds: number;
  formattedScheduledTime: string;
  state: "countdown" | "due" | "started";
  runId: string | null;
  dismissCountdown: () => void;
}

export interface ActiveApprovalAlert {
  runId: string;
  scheduleName?: string;
  operation: string;
  title: string;
  message: string;
  dismissApprovalAlert: () => void;
}

interface NotificationContextType {
  notifications: AppNotification[];
  unreadCount: number;
  isLoading: boolean;
  activeCountdown: ActiveCountdown | null;
  activeApprovalAlert: ActiveApprovalAlert | null;
  browserPermission: NotificationPermission;
  requestBrowserPermission: () => Promise<void>;
  markAsRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  dismissNotification: (id: string) => Promise<void>;
  dismissActiveCountdown: () => void;
  dismissActiveApproval: () => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [activeCountdown, setActiveCountdown] = useState<ActiveCountdown | null>(null);
  const [activeApprovalAlert, setActiveApprovalAlert] = useState<ActiveApprovalAlert | null>(null);
  const [browserPermission, setBrowserPermission] = useState<NotificationPermission>("default");

  // Track occurrences already notified to avoid repeated triggers
  const notifiedOccurrences = useRef<Set<string>>(new Set());
  const dismissedCountdowns = useRef<Set<string>>(new Set());
  const dismissedApprovals = useRef<Set<string>>(new Set());

  // Check initial Notification API permission state
  useEffect(() => {
    if (typeof window !== "undefined" && "Notification" in window) {
      setBrowserPermission(Notification.permission);
    }
  }, []);

  // 1. Fetch persistent notifications for the authenticated user
  const {
    data: notifData,
    isLoading,
  } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.notifications.listNotifications(50),
    enabled: !!user,
    staleTime: 5000,
    refetchInterval: 10000,
  });

  const notifications = notifData?.items || [];
  const unreadCount = notifData?.unread_count ?? 0;

  // 2. Poll active schedules for 15-second countdown detection
  const { data: schedules = [] } = useQuery<ScheduledWorkflow[]>({
    queryKey: ["schedules"],
    queryFn: () => api.schedules.listSchedules(),
    enabled: !!user,
    staleTime: 5000,
    refetchInterval: 10000,
  });

  // 3. Poll pending approvals
  const { data: pendingApprovalsData } = useQuery<{ items: AgentRun[] }>({
    queryKey: ["approvals", "pending"],
    queryFn: () => api.workflows.listRuns({ status: "awaiting_approval", limit: 10 }),
    enabled: !!user,
    staleTime: 4000,
    refetchInterval: 8000,
  });

  const pendingApprovals = useMemo(
    () => pendingApprovalsData?.items || [],
    [pendingApprovalsData?.items]
  );

  // Helper to trigger browser notification if explicitly permitted
  const sendDesktopNotification = useCallback((title: string, body: string, url?: string) => {
    if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
      try {
        const notif = new Notification(title, {
          body,
          icon: "/favicon.ico",
        });
        if (url) {
          notif.onclick = () => {
            window.focus();
            window.location.href = url;
          };
        }
      } catch (err) {
        console.error("Desktop notification dispatch error:", err);
      }
    }
  }, []);

  // Request browser permission ONLY upon explicit user interaction
  const requestBrowserPermission = async () => {
    if (typeof window === "undefined" || !("Notification" in window)) {
      return;
    }
    try {
      const res = await Notification.requestPermission();
      setBrowserPermission(res);
      if (res === "granted") {
        sendDesktopNotification("FlowPilot AI Alerts Enabled", "You will receive desktop alerts for scheduled executions and approvals.");
      }
    } catch (err) {
      console.error("Notification permission request error:", err);
    }
  };

  // Authoritative 1-second interval loop for countdown calculation
  useEffect(() => {
    if (!user || schedules.length === 0) {
      return;
    }

    const intervalId = setInterval(() => {
      const now = Date.now();

      // Find an active schedule within the 15-second countdown window:
      // (next_run_at - now <= 15000) and (now - next_run_at <= 60000)
      let foundCountdownCandidate: {
        schedule: ScheduledWorkflow;
        targetTime: number;
        remainingSec: number;
        occurrenceKey: string;
      } | null = null;

      for (const sched of schedules) {
        if (!sched.is_active || !sched.next_run_at) continue;

        const targetTime = new Date(sched.next_run_at).getTime();
        const diffMs = targetTime - now;

        // Window: from 15.0 seconds before due time, up to 60 seconds past due time
        if (diffMs <= 15000 && diffMs >= -60000) {
          const occurrenceKey = `${sched.id}:${sched.next_run_at}`;
          if (dismissedCountdowns.current.has(occurrenceKey)) {
            continue;
          }

          const remainingSec = Math.max(0, Math.floor(diffMs / 1000));
          foundCountdownCandidate = {
            schedule: sched,
            targetTime,
            remainingSec,
            occurrenceKey,
          };
          break;
        }
      }

      if (foundCountdownCandidate) {
        const { schedule, targetTime, remainingSec, occurrenceKey } = foundCountdownCandidate;

        // Record persistent notification on initial detection
        if (!notifiedOccurrences.current.has(occurrenceKey)) {
          notifiedOccurrences.current.add(occurrenceKey);

          // Persist to backend notifications
          api.notifications
            .createNotification({
              type: "schedule_countdown",
              category: "schedule",
              title: "Upcoming Workflow",
              message: `Your scheduled workflow "${schedule.name}" is approaching its execution time.`,
              dedup_key: `countdown_${occurrenceKey}`,
              link_url: "/schedules",
              meta_data: {
                schedule_id: schedule.id,
                schedule_name: schedule.name,
                next_run_at: schedule.next_run_at,
              },
            })
            .then(() => {
              queryClient.invalidateQueries({ queryKey: ["notifications"] });
            })
            .catch(() => {});

          // Optional desktop notification
          sendDesktopNotification(
            `Upcoming Workflow: ${schedule.name}`,
            "Your scheduled workflow is approaching its execution time in 15 seconds.",
            "/schedules"
          );
        }

        // Format scheduled time for display
        const targetDate = new Date(targetTime);
        const formattedScheduledTime = targetDate.toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
        });

        // Determine state
        let state: "countdown" | "due" | "started" = "countdown";
        const runId: string | null = schedule.latest_run_id || null;

        if (remainingSec === 0) {
          if (runId) {
            state = "started";
          } else {
            state = "due";
          }
        }

        setActiveCountdown((prev) => {
          if (
            prev?.scheduleId === schedule.id &&
            prev?.remainingSeconds === remainingSec &&
            prev?.state === state &&
            prev?.runId === runId
          ) {
            return prev;
          }
          return {
            scheduleId: schedule.id,
            scheduleName: schedule.name,
            targetTimestamp: targetTime,
            remainingSeconds: remainingSec,
            formattedScheduledTime,
            state,
            runId,
            dismissCountdown: () => {
              dismissedCountdowns.current.add(occurrenceKey);
              setActiveCountdown(null);
            },
          };
        });
      } else {
        // If no schedule in countdown window, clear countdown if it wasn't recently completed
        setActiveCountdown((prev) => (prev ? null : prev));
      }
    }, 1000);

    return () => clearInterval(intervalId);
  }, [user, schedules, queryClient, sendDesktopNotification]);

  // Monitor pending approvals
  useEffect(() => {
    if (!user || pendingApprovals.length === 0) {
      setActiveApprovalAlert((prev) => (prev ? null : prev));
      return;
    }

    const firstPending = pendingApprovals[0];
    const runId = firstPending.id;

    if (dismissedApprovals.current.has(runId)) {
      return;
    }

    // Determine sensitive operation from execution plan
    const sensitiveStep = (firstPending.execution_plan || []).find(
      (s: any) => s.approval_required || s.status === "awaiting_approval"
    );
    const operation = sensitiveStep?.operation || "sensitive operation";

    setActiveApprovalAlert((prev) => {
      if (prev?.runId === runId && prev?.operation === operation) {
        return prev;
      }
      return {
        runId,
        operation,
        title: "Approval Required",
        message: `Workflow execution is waiting for authorization to execute ${operation}.`,
        dismissApprovalAlert: () => {
          dismissedApprovals.current.add(runId);
          setActiveApprovalAlert(null);
        },
      };
    });

    // Optional desktop notification
    if (!notifiedOccurrences.current.has(`approval_${runId}`)) {
      notifiedOccurrences.current.add(`approval_${runId}`);
      sendDesktopNotification(
        "Approval Required",
        `A scheduled workflow is paused and awaiting human approval for ${operation}.`,
        `/approvals?run_id=${runId}`
      );
    }
  }, [user, pendingApprovals, sendDesktopNotification]);

  const markAsRead = async (id: string) => {
    await api.notifications.markAsRead(id);
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };

  const markAllRead = async () => {
    await api.notifications.markAllRead();
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };

  const dismissNotification = async (id: string) => {
    await api.notifications.dismissNotification(id);
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };

  const dismissActiveCountdown = () => {
    if (activeCountdown) {
      activeCountdown.dismissCountdown();
    }
  };

  const dismissActiveApproval = () => {
    if (activeApprovalAlert) {
      activeApprovalAlert.dismissApprovalAlert();
    }
  };

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        unreadCount,
        isLoading,
        activeCountdown,
        activeApprovalAlert,
        browserPermission,
        requestBrowserPermission,
        markAsRead,
        markAllRead,
        dismissNotification,
        dismissActiveCountdown,
        dismissActiveApproval,
      }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (!context) {
    return {
      notifications: [],
      unreadCount: 0,
      isLoading: false,
      activeCountdown: null,
      activeApprovalAlert: null,
      browserPermission: "default" as NotificationPermission,
      requestBrowserPermission: async () => {},
      markAsRead: async () => {},
      markAllRead: async () => {},
      dismissNotification: async () => {},
      dismissActiveCountdown: () => {},
      dismissActiveApproval: () => {},
    };
  }
  return context;
}
