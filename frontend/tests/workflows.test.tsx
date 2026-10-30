import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WorkflowsPage from "@/app/(dashboard)/workflows/page";
import { api, ApiError } from "@/lib/api/client";
import { toast } from "sonner";

// Mock router
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

// Mock toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

// Mock api client
vi.mock("@/lib/api/client", () => {
  class MockApiError extends Error {
    status: number;
    data: any;
    constructor(message: string, status: number, data?: any) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.data = data;
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      workflows: {
        createRun: vi.fn(),
      },
      llm: {
        listCredentials: vi.fn().mockResolvedValue([]),
        discoverModels: vi.fn().mockResolvedValue([]),
      },
    },
  };
});

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("Workflows Page - Submission Lifecycle and Stability Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders workflow input and starter templates in idle state", () => {
    renderWithClient(<WorkflowsPage />);

    expect(screen.getByText("New Workflow Execution")).toBeInTheDocument();
    const textarea = screen.getByPlaceholderText(/Describe what you want the multi-agent system to accomplish/i);
    expect(textarea).toBeInTheDocument();
    expect(screen.getByText("Weekly Ops Briefing")).toBeInTheDocument();

    const submitBtn = screen.getByRole("button", { name: /Execute Workflow/i });
    expect(submitBtn).toBeInTheDocument();
    expect(submitBtn).not.toBeDisabled();
  });

  it("populates prompt when clicking a template preset", () => {
    renderWithClient(<WorkflowsPage />);

    const templateBtn = screen.getByText("Weekly Ops Briefing");
    fireEvent.click(templateBtn);

    const textarea = screen.getByPlaceholderText(/Describe what you want the multi-agent system to accomplish/i) as HTMLTextAreaElement;
    expect(textarea.value).toContain("Fetch system health metrics from monitoring");
  });

  it("submits workflow request, handles HTTP 202, releases loading state, and navigates", async () => {
    (api.workflows.createRun as any).mockResolvedValueOnce({
      id: "run-test-uuid-123",
      status: "queued",
      original_request: "Send a daily report to Slack",
    });

    renderWithClient(<WorkflowsPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you want the multi-agent system to accomplish/i);
    fireEvent.change(textarea, {
      target: { value: "Send a daily report to Slack" },
    });

    const submitBtn = screen.getByRole("button", { name: /Execute Workflow/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.workflows.createRun).toHaveBeenCalledWith({
        request: "Send a daily report to Slack",
      });
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("HTTP 202 Accepted"));
      expect(mockPush).toHaveBeenCalledWith("/executions/run-test-uuid-123");
    });

    // Verify button is not permanently stuck loading
    await waitFor(() => {
      expect(submitBtn).not.toBeDisabled();
    });
  });

  it("prevents double-click duplicate submission while in flight", async () => {
    let resolvePromise: (val: any) => void = () => {};
    const pendingPromise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    (api.workflows.createRun as any).mockReturnValueOnce(pendingPromise);

    renderWithClient(<WorkflowsPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you want the multi-agent system to accomplish/i);
    fireEvent.change(textarea, {
      target: { value: "Send a daily report to Slack" },
    });

    const submitBtn = screen.getByRole("button", { name: /Execute Workflow/i });
    // First click triggers submission
    fireEvent.click(submitBtn);
    expect(api.workflows.createRun).toHaveBeenCalledTimes(1);

    // Second click during in-flight submission must be ignored
    fireEvent.click(submitBtn);
    expect(api.workflows.createRun).toHaveBeenCalledTimes(1);

    // Resolve in-flight submission
    resolvePromise({ id: "run-uuid-double-click", status: "queued" });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/executions/run-uuid-double-click");
    });
  });

  it("resets loading state on submission error (HTTP 400/401/422/500) and preserves input", async () => {
    (api.workflows.createRun as any).mockRejectedValueOnce(
      new ApiError("LLM Provider authentication failed.", 401)
    );

    renderWithClient(<WorkflowsPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you want the multi-agent system to accomplish/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, {
      target: { value: "Send email with sensitive data to operator" },
    });

    const submitBtn = screen.getByRole("button", { name: /Execute Workflow/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("LLM Provider authentication failed.");
    });

    // Form input must remain intact
    expect(textarea.value).toBe("Send email with sensitive data to operator");

    // Button loading state must be released without full page refresh
    await waitFor(() => {
      expect(submitBtn).not.toBeDisabled();
    });
  });

  it("handles request timeout gracefully and resets button state", async () => {
    (api.workflows.createRun as any).mockRejectedValueOnce(
      new ApiError(
        "Request timed out while waiting for server response. Please verify execution history before retrying.",
        408
      )
    );

    renderWithClient(<WorkflowsPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you want the multi-agent system to accomplish/i);
    fireEvent.change(textarea, {
      target: { value: "Execute long-running synchronization" },
    });

    const submitBtn = screen.getByRole("button", { name: /Execute Workflow/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Request timed out while waiting for server response")
      );
    });

    // Loading state is released, button is usable again
    await waitFor(() => {
      expect(submitBtn).not.toBeDisabled();
    });
  });

  it("rejects short inputs without triggering network requests", async () => {
    renderWithClient(<WorkflowsPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you want the multi-agent system to accomplish/i);
    fireEvent.change(textarea, {
      target: { value: "Hey" },
    });

    const submitBtn = screen.getByRole("button", { name: /Execute Workflow/i });
    fireEvent.click(submitBtn);

    expect(api.workflows.createRun).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("minimum 5 characters"));
    expect(submitBtn).not.toBeDisabled();
  });
});
