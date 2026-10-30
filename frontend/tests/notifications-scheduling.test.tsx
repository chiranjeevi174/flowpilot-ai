import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SchedulesPage from "@/app/(dashboard)/schedules/page";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { GlobalNotificationBanner } from "@/components/notifications/global-notification-banner";
import { NotificationProvider } from "@/lib/notifications/notification-context";
import { api } from "@/lib/api/client";

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
}));

// Mock auth context
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "operator@example.com", full_name: "Test Operator" },
    isLoading: false,
    logout: vi.fn(),
  }),
}));

// Mock api client
vi.mock("@/lib/api/client", () => ({
  api: {
    schedules: {
      listSchedules: vi.fn(),
      pauseSchedule: vi.fn(),
      resumeSchedule: vi.fn(),
      deleteSchedule: vi.fn(),
      createSchedule: vi.fn(),
    },
    notifications: {
      listNotifications: vi.fn(),
      markAsRead: vi.fn(),
      markAllRead: vi.fn(),
      dismissNotification: vi.fn(),
      createNotification: vi.fn(),
    },
    workflows: {
      listRuns: vi.fn(),
    },
  },
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationProvider>{ui}</NotificationProvider>
    </QueryClientProvider>
  );
}

describe("Smart Scheduling & Notification System", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Schedule Page — Active Schedules vs Schedule History", () => {
    const mockSchedules = [
      {
        id: "sched-active-recurring",
        user_id: "user-1",
        name: "Daily Analytics Digest",
        workflow_request: "Summarize daily metrics",
        schedule_type: "daily" as const,
        timezone: "UTC",
        schedule_configuration: { time: "09:00" },
        is_active: true,
        next_run_at: "2026-10-29T09:00:00Z",
        last_run_at: "2026-10-28T09:00:00Z",
        created_at: "2026-10-20T00:00:00Z",
        updated_at: "2026-10-28T09:00:00Z",
      },
      {
        id: "sched-paused-recurring",
        user_id: "user-1",
        name: "Weekly Customer Sync",
        workflow_request: "Sync customer database",
        schedule_type: "weekly" as const,
        timezone: "UTC",
        schedule_configuration: { time: "10:00", days_of_week: [1] },
        is_active: false,
        next_run_at: "2026-11-02T10:00:00Z",
        last_run_at: null,
        created_at: "2026-10-21T00:00:00Z",
        updated_at: "2026-10-21T00:00:00Z",
      },
      {
        id: "sched-upcoming-onetime",
        user_id: "user-1",
        name: "Quarterly Audit",
        workflow_request: "Run security and permission audit",
        schedule_type: "one_time" as const,
        timezone: "UTC",
        schedule_configuration: { run_at: "2026-11-01T15:00:00Z" },
        is_active: true,
        next_run_at: "2026-11-01T15:00:00Z",
        last_run_at: null, // Not yet triggered!
        created_at: "2026-10-25T00:00:00Z",
        updated_at: "2026-10-25T00:00:00Z",
      },
      {
        id: "sched-completed-onetime",
        user_id: "user-1",
        name: "One-Time Product Announcement",
        workflow_request: "Dispatch email announcement to VIP beta users",
        schedule_type: "one_time" as const,
        timezone: "UTC",
        schedule_configuration: { run_at: "2026-10-28T12:00:00Z" },
        is_active: false, // Marked false by scheduler when claimed!
        next_run_at: "2026-10-28T12:00:00Z",
        last_run_at: "2026-10-28T12:00:05Z", // Triggered!
        created_at: "2026-10-27T10:00:00Z",
        updated_at: "2026-10-28T12:00:05Z",
        latest_run_id: "run-announcement-uuid-99",
        latest_run_status: "completed",
      },
    ];

    it("renders Active Schedules by default and excludes completed one-time schedules", async () => {
      (api.schedules.listSchedules as any).mockResolvedValue(mockSchedules);

      renderWithClient(<SchedulesPage />);

      await waitFor(() => {
        expect(screen.getByText("Daily Analytics Digest")).toBeInTheDocument();
      });

      // Active schedules should contain recurring and upcoming one-time
      expect(screen.getByText("Weekly Customer Sync")).toBeInTheDocument();
      expect(screen.getByText("Quarterly Audit")).toBeInTheDocument();

      // Completed one-time schedule MUST NOT appear in Active Schedules tab
      expect(screen.queryByText("One-Time Product Announcement")).not.toBeInTheDocument();
    });

    it("displays completed one-time schedule in Schedule History tab with execution link", async () => {
      (api.schedules.listSchedules as any).mockResolvedValue(mockSchedules);

      renderWithClient(<SchedulesPage />);

      await waitFor(() => {
        expect(screen.getByText("Schedule History")).toBeInTheDocument();
      });

      // Switch to Schedule History tab
      const historyTab = screen.getByText("Schedule History");
      fireEvent.click(historyTab);

      // Now the completed schedule should be visible
      await waitFor(() => {
        expect(screen.getByText("One-Time Product Announcement")).toBeInTheDocument();
      });

      // Check for Completed lifecycle badge and View Run button
      expect(screen.getByText("Completed")).toBeInTheDocument();
      expect(screen.getByText("View Run")).toBeInTheDocument();

      // Active ones should NOT be in History
      expect(screen.queryByText("Quarterly Audit")).not.toBeInTheDocument();
      expect(screen.queryByText("Daily Analytics Digest")).not.toBeInTheDocument();
    });
  });

  describe("Notification Bell Component", () => {
    const mockNotifications = [
      {
        id: "notif-1",
        user_id: "user-1",
        type: "approval_required" as const,
        category: "approval" as const,
        title: "Approval Required",
        message: "Your workflow is waiting for authorization to execute whatsapp_send_template.",
        link_url: "/approvals?run_id=run-123",
        meta_data: { run_id: "run-123", operation: "whatsapp_send_template" },
        dedup_key: "approval_run-123",
        is_read: false,
        is_dismissed: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ];

    it("renders notification bell with unread badge and toggles popover", async () => {
      (api.notifications.listNotifications as any).mockResolvedValue({
        items: mockNotifications,
        unread_count: 1,
        total: 1,
      });
      (api.schedules.listSchedules as any).mockResolvedValue([]);
      (api.workflows.listRuns as any).mockResolvedValue({ items: [] });

      renderWithClient(<NotificationBell />);

      await waitFor(() => {
        expect(screen.getByText("1")).toBeInTheDocument();
      });

      // Click bell to open popover
      const bellButton = screen.getByLabelText("View notifications");
      fireEvent.click(bellButton);

      await waitFor(() => {
        expect(screen.getByText("Notifications")).toBeInTheDocument();
        expect(screen.getByText("Approval Required")).toBeInTheDocument();
      });
    });
  });

  describe("Global Notification Banner — Approvals & Live Countdown", () => {
    it("renders Approval Required banner when workflow reaches awaiting_approval", async () => {
      (api.notifications.listNotifications as any).mockResolvedValue({
        items: [],
        unread_count: 0,
        total: 0,
      });
      (api.schedules.listSchedules as any).mockResolvedValue([]);
      (api.workflows.listRuns as any).mockResolvedValue({
        items: [
          {
            id: "run-approval-pending-99",
            status: "awaiting_approval",
            original_request: "Send WhatsApp message to client",
            execution_plan: [
              {
                step_id: "step-1",
                operation: "whatsapp_send_direct",
                approval_required: true,
              },
            ],
          },
        ],
      });

      renderWithClient(<GlobalNotificationBanner />);

      await waitFor(() => {
        expect(screen.getAllByText("Approval Required").length).toBeGreaterThan(0);
        expect(screen.getByText("Open Approval")).toBeInTheDocument();
        expect(screen.getByText("Dismiss")).toBeInTheDocument();
      });

      // Clicking Open Approval navigates to /approvals?run_id=...
      const openButton = screen.getByText("Open Approval");
      fireEvent.click(openButton);
      expect(mockPush).toHaveBeenCalledWith("/approvals?run_id=run-approval-pending-99");
    });
  });
});
