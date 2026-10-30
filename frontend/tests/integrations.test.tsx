import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import IntegrationsPage from "@/app/(dashboard)/integrations/page";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
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
    },
  },
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("Integrations Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders integration providers and connected status", async () => {
    (api.integrations.listProviders as any).mockResolvedValueOnce([
      { id: "google", name: "Google", category: "productivity", is_configured: true, supported_services: ["gmail", "sheets"], supported_scopes: [] },
      { id: "slack", name: "Slack", category: "chat", is_configured: true, supported_services: ["chat"], supported_scopes: [] },
    ]);
    (api.integrations.listConnections as any).mockResolvedValueOnce([
      {
        id: "conn-slack-1",
        user_id: "user-1",
        provider: "slack",
        service: null,
        external_account_name: "Acme Corp Slack",
        granted_scopes: ["chat:write"],
        token_expires_at: null,
        status: "active",
        last_verified_at: new Date().toISOString(),
        metadata_json: {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);
    (api.integrations.listActions as any).mockResolvedValueOnce([]);

    renderWithClient(<IntegrationsPage />);

    await waitFor(() => {
      expect(screen.getByText("Google (Gmail)")).toBeInTheDocument();
      expect(screen.getByText("Google Sheets")).toBeInTheDocument();
      expect(screen.getByText("Slack")).toBeInTheDocument();
      expect(screen.getByText("Acme Corp Slack")).toBeInTheDocument();
    });
  });

  it("triggers connection test", async () => {
    (api.integrations.listProviders as any).mockResolvedValue([
      { id: "slack", name: "Slack", is_configured: true, supported_services: [], supported_scopes: [] },
    ]);
    (api.integrations.listConnections as any).mockResolvedValue([
      {
        id: "conn-slack-1",
        provider: "slack",
        external_account_name: "Acme Corp Slack",
        status: "active",
        granted_scopes: [],
        metadata_json: {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);
    (api.integrations.listActions as any).mockResolvedValue([]);
    (api.integrations.testConnection as any).mockResolvedValueOnce({
      id: "conn-slack-1",
      provider: "slack",
      status: "verified",
      message: "Slack connection verified",
    });

    renderWithClient(<IntegrationsPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Test/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Test/i }));

    await waitFor(() => {
      expect(api.integrations.testConnection).toHaveBeenCalledWith("conn-slack-1");
    });
  });
});
