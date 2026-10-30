import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SchedulesPage from "@/app/(dashboard)/schedules/page";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    schedules: {
      listSchedules: vi.fn(),
      createSchedule: vi.fn(),
      pauseSchedule: vi.fn(),
      resumeSchedule: vi.fn(),
      deleteSchedule: vi.fn(),
    },
    workflows: {
      createRun: vi.fn(),
    },
  },
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("Schedules Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders scheduled workflows list", async () => {
    (api.schedules.listSchedules as any).mockResolvedValueOnce([
      {
        id: "sched-1",
        user_id: "user-1",
        name: "Morning Ops Briefing",
        workflow_request: "Summarize tickets and alert Slack",
        schedule_type: "daily",
        timezone: "UTC",
        schedule_configuration: { time: "08:30" },
        is_active: true,
        next_run_at: new Date().toISOString(),
        last_run_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);

    renderWithClient(<SchedulesPage />);

    await waitFor(() => {
      expect(screen.getByText("Morning Ops Briefing")).toBeInTheDocument();
      expect(screen.getByText("Active")).toBeInTheDocument();
      expect(screen.getByText(/Daily at 08:30 UTC/i)).toBeInTheDocument();
    });
  });

  it("pauses an active schedule", async () => {
    (api.schedules.listSchedules as any).mockResolvedValue([
      {
        id: "sched-1",
        user_id: "user-1",
        name: "Morning Ops Briefing",
        workflow_request: "Summarize tickets and alert Slack",
        schedule_type: "daily",
        timezone: "UTC",
        schedule_configuration: { time: "08:30" },
        is_active: true,
        next_run_at: new Date().toISOString(),
        last_run_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);
    (api.schedules.pauseSchedule as any).mockResolvedValueOnce({
      id: "sched-1",
      name: "Morning Ops Briefing",
      is_active: false,
    });

    renderWithClient(<SchedulesPage />);

    await waitFor(() => {
      expect(screen.getByTitle("Pause Schedule")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle("Pause Schedule"));

    await waitFor(() => {
      expect(api.schedules.pauseSchedule).toHaveBeenCalledWith("sched-1");
    });
  });
});
