import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ApprovalsPage from "@/app/(dashboard)/approvals/page";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    workflows: {
      listRuns: vi.fn(),
      approveRun: vi.fn(),
      rejectRun: vi.fn(),
    },
  },
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("Approvals Page", () => {
  const mockPendingRun = {
    id: "run-approve-12345678",
    user_id: "user-1",
    thread_id: "thread-1",
    original_request: "Notify all customers via Gmail",
    status: "awaiting_approval" as const,
    current_step: 0,
    detected_intent: { intent: "email_dispatch", action: "send_mass_email" },
    execution_plan: [
      {
        step_id: "step-1",
        operation: "gmail_send_email",
        parameters: { recipient: "all@enterprise.com", subject: "Product Launch" },
        required_capability: "email",
        approval_required: true,
        expected_outcome: "Emails dispatched to customer list",
      },
    ],
    final_result: null,
    error_message: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("displays pending approval card with parameter preview", async () => {
    (api.workflows.listRuns as any).mockResolvedValueOnce({
      items: [mockPendingRun],
      total: 1,
      limit: 50,
      offset: 0,
    });

    renderWithClient(<ApprovalsPage />);

    await waitFor(() => {
      expect(screen.getByText("Notify all customers via Gmail")).toBeInTheDocument();
      expect(screen.getByText("gmail_send_email")).toBeInTheDocument();
      expect(screen.getByText(/Emails dispatched to customer list/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Approve & Resume/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Reject & Abort/i })).toBeInTheDocument();
    });
  });

  it("opens confirmation dialog and executes approval", async () => {
    (api.workflows.listRuns as any).mockResolvedValue({
      items: [mockPendingRun],
      total: 1,
      limit: 50,
      offset: 0,
    });
    (api.workflows.approveRun as any).mockResolvedValueOnce({
      ...mockPendingRun,
      status: "running",
    });

    renderWithClient(<ApprovalsPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Approve & Resume/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Approve & Resume/i }));

    // Modal opens
    expect(screen.getByText("Approve Proposed Action")).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: "Confirm Approval" });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(api.workflows.approveRun).toHaveBeenCalledWith("run-approve-12345678", undefined);
    });
  });
});
