import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import IntegrationsPage from "@/app/(dashboard)/integrations/page";
import ApprovalsPage from "@/app/(dashboard)/approvals/page";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    integrations: {
      listProviders: vi.fn(),
      listConnections: vi.fn(),
      listActions: vi.fn(),
      testConnection: vi.fn(),
      disconnectConnection: vi.fn(),
      getAuthorizeUrl: vi.fn(),
      getWhatsAppStatus: vi.fn(),
      testWhatsApp: vi.fn(),
    },
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

describe("WhatsApp Integration UI Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("WhatsApp Integration Card on Integrations Page", () => {
    it("renders WhatsApp card in configured state with masked credentials and test button", async () => {
      (api.integrations.listProviders as any).mockResolvedValueOnce([
        {
          id: "google",
          name: "Google",
          category: "productivity",
          is_configured: true,
          supported_services: ["gmail", "sheets"],
          supported_scopes: [],
        },
        {
          id: "slack",
          name: "Slack",
          category: "chat",
          is_configured: true,
          supported_services: ["chat"],
          supported_scopes: [],
        },
        {
          id: "whatsapp",
          name: "WhatsApp Business",
          category: "messaging",
          is_configured: true,
          auth_type: "system_credentials",
          supported_services: ["messages", "templates"],
          supported_scopes: [],
        },
      ]);
      (api.integrations.listConnections as any).mockResolvedValueOnce([]);
      (api.integrations.listActions as any).mockResolvedValueOnce([]);
      (api.integrations.getWhatsAppStatus as any).mockResolvedValueOnce({
        is_configured: true,
        phone_number_id_configured: true,
        masked_phone_number_id: "••••6344",
        business_account_id_configured: true,
        masked_business_account_id: "••••4321",
        graph_api_version: "v21.0",
        webhook_verify_token_configured: true,
        app_secret_configured: true,
        missing_fields: [],
        supported_capabilities: ["whatsapp_send_message", "whatsapp_send_template"],
      });

      renderWithClient(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByText("WhatsApp Business")).toBeInTheDocument();
        expect(screen.getByText("••••6344")).toBeInTheDocument();
        expect(screen.getByText("••••4321")).toBeInTheDocument();
        expect(screen.getByText("v21.0")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Test Connection/i })).toBeInTheDocument();
      });
    });

    it("renders missing environment variables when WhatsApp is not configured", async () => {
      (api.integrations.listProviders as any).mockResolvedValueOnce([]);
      (api.integrations.listConnections as any).mockResolvedValueOnce([]);
      (api.integrations.listActions as any).mockResolvedValueOnce([]);
      (api.integrations.getWhatsAppStatus as any).mockResolvedValueOnce({
        is_configured: false,
        phone_number_id_configured: false,
        masked_phone_number_id: null,
        business_account_id_configured: false,
        masked_business_account_id: null,
        graph_api_version: "v21.0",
        webhook_verify_token_configured: false,
        app_secret_configured: false,
        missing_fields: [
          "WHATSAPP_PHONE_NUMBER_ID",
          "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_APP_SECRET",
        ],
        supported_capabilities: ["whatsapp_send_message", "whatsapp_send_template"],
      });

      renderWithClient(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByText("WhatsApp Business")).toBeInTheDocument();
        expect(screen.getByText("Missing Backend Credentials")).toBeInTheDocument();
        expect(screen.getByText("WHATSAPP_PHONE_NUMBER_ID")).toBeInTheDocument();
        expect(screen.getByText("WHATSAPP_ACCESS_TOKEN")).toBeInTheDocument();
        expect(screen.getByText("WHATSAPP_APP_SECRET")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Setup Instructions/i })).toBeInTheDocument();
      });
    });

    it("triggers WhatsApp connection test mutation when clicked", async () => {
      (api.integrations.listProviders as any).mockResolvedValue([
        { id: "whatsapp", is_configured: true, supported_services: [], supported_scopes: [] },
      ]);
      (api.integrations.listConnections as any).mockResolvedValue([]);
      (api.integrations.listActions as any).mockResolvedValue([]);
      (api.integrations.getWhatsAppStatus as any).mockResolvedValue({
        is_configured: true,
        phone_number_id_configured: true,
        masked_phone_number_id: "••••6344",
        business_account_id_configured: true,
        masked_business_account_id: "••••4321",
        graph_api_version: "v21.0",
        webhook_verify_token_configured: true,
        app_secret_configured: true,
        missing_fields: [],
        supported_capabilities: ["whatsapp_send_message", "whatsapp_send_template"],
      });
      (api.integrations.testWhatsApp as any).mockResolvedValueOnce({
        ok: true,
        id: "meta_phone_test",
        provider: "whatsapp",
        status: "verified",
        message: "Meta Cloud API credentials verified successfully.",
      });

      renderWithClient(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Test Connection/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /Test Connection/i }));

      await waitFor(() => {
        expect(api.integrations.testWhatsApp).toHaveBeenCalledTimes(1);
      });
    });

    it("opens setup instructions dialog when clicking Guide or Setup Instructions", async () => {
      (api.integrations.listProviders as any).mockResolvedValueOnce([]);
      (api.integrations.listConnections as any).mockResolvedValueOnce([]);
      (api.integrations.listActions as any).mockResolvedValueOnce([]);
      (api.integrations.getWhatsAppStatus as any).mockResolvedValueOnce({
        is_configured: false,
        phone_number_id_configured: false,
        masked_phone_number_id: null,
        business_account_id_configured: false,
        masked_business_account_id: null,
        graph_api_version: "v21.0",
        webhook_verify_token_configured: false,
        app_secret_configured: false,
        missing_fields: ["WHATSAPP_PHONE_NUMBER_ID"],
        supported_capabilities: [],
      });

      renderWithClient(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Setup Instructions/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /Setup Instructions/i }));

      expect(screen.getByText("WhatsApp Business Cloud API Setup")).toBeInTheDocument();
      expect(screen.getByText(/1. Meta Developer Portal Setup/i)).toBeInTheDocument();
      expect(screen.getByText(/2. Environment Variables/i)).toBeInTheDocument();
      expect(screen.getByText(/3. Webhook Configuration/i)).toBeInTheDocument();
    });
  });

  describe("WhatsApp Human-in-the-Loop Approvals UI", () => {
    const mockWhatsAppMessageRun = {
      id: "run-wa-msg-12345678",
      user_id: "user-1",
      thread_id: "thread-wa-1",
      original_request: "Send customer notification via WhatsApp",
      status: "awaiting_approval" as const,
      current_step: 0,
      detected_intent: { intent: "customer_support", action: "whatsapp_send" },
      execution_plan: [
        {
          step_id: "step-wa-1",
          operation: "whatsapp_send_message",
          parameters: {
            to: "+1 (555) 012-3456",
            message: "Hello John, your order #94821 has been verified and dispatched.",
          },
          required_capability: "whatsapp",
          approval_required: true,
          expected_outcome: "Customer receives WhatsApp order status update",
        },
      ],
      final_result: null,
      error_message: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    const mockWhatsAppTemplateRun = {
      id: "run-wa-tmpl-87654321",
      user_id: "user-1",
      thread_id: "thread-wa-2",
      original_request: "Send invoice alert via approved WhatsApp template",
      status: "awaiting_approval" as const,
      current_step: 0,
      detected_intent: { intent: "billing", action: "template_dispatch" },
      execution_plan: [
        {
          step_id: "step-wa-2",
          operation: "whatsapp_send_template",
          parameters: {
            to: "15551234567",
            template_name: "order_confirmation_v2",
            language_code: "en_US",
            parameters: { order_id: "94821", total: "$120.00" },
          },
          required_capability: "whatsapp",
          approval_required: true,
          expected_outcome: "Pre-approved WhatsApp template sent to recipient",
        },
      ],
      final_result: null,
      error_message: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    it("renders rich WhatsApp direct message preview with recipient and bubble", async () => {
      (api.workflows.listRuns as any).mockResolvedValueOnce({
        items: [mockWhatsAppMessageRun],
        total: 1,
        limit: 50,
        offset: 0,
      });

      renderWithClient(<ApprovalsPage />);

      await waitFor(() => {
        expect(screen.getByText("Send customer notification via WhatsApp")).toBeInTheDocument();
        expect(screen.getByText("WhatsApp Business Dispatch")).toBeInTheDocument();
        expect(screen.getByText("+1 (555) 012-3456")).toBeInTheDocument();
        expect(screen.getByText("E.164 Validated")).toBeInTheDocument();
        expect(
          screen.getByText("Hello John, your order #94821 has been verified and dispatched.")
        ).toBeInTheDocument();
        expect(screen.getByText("Digest Protected")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Approve & Resume/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Reject & Abort/i })).toBeInTheDocument();
      });
    });

    it("renders WhatsApp template approval with template name, language, and params", async () => {
      (api.workflows.listRuns as any).mockResolvedValueOnce({
        items: [mockWhatsAppTemplateRun],
        total: 1,
        limit: 50,
        offset: 0,
      });

      renderWithClient(<ApprovalsPage />);

      await waitFor(() => {
        expect(
          screen.getByText("Send invoice alert via approved WhatsApp template")
        ).toBeInTheDocument();
        expect(screen.getByText("order_confirmation_v2")).toBeInTheDocument();
        expect(screen.getByText("en_US")).toBeInTheDocument();
        expect(screen.getByText("15551234567")).toBeInTheDocument();
      });
    });

    it("allows approving WhatsApp workflow through existing authorization system", async () => {
      (api.workflows.listRuns as any).mockResolvedValue({
        items: [mockWhatsAppMessageRun],
        total: 1,
        limit: 50,
        offset: 0,
      });
      (api.workflows.approveRun as any).mockResolvedValueOnce({
        ...mockWhatsAppMessageRun,
        status: "running",
      });

      renderWithClient(<ApprovalsPage />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Approve & Resume/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /Approve & Resume/i }));

      expect(screen.getByText("Approve Proposed Action")).toBeInTheDocument();

      const confirmBtn = screen.getByRole("button", { name: "Confirm Approval" });
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(api.workflows.approveRun).toHaveBeenCalledWith("run-wa-msg-12345678", undefined);
      });
    });
  });
});
