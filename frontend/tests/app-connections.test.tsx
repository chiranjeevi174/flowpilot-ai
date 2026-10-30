import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AppConnectionsPage from "@/app/(dashboard)/settings/connections/page";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    connections: {
      getOverview: vi.fn(),
      getSetupGuides: vi.fn(),
      getSetupGuide: vi.fn(),
      saveCredentials: vi.fn(),
      setDefault: vi.fn(),
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

describe("App Connections Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockOverview = [
    {
      id: "gmail",
      name: "Gmail",
      category: "Email Automation",
      icon: "mail",
      description: "Automate email notifications, draft creation, and mailbox inbox inspection.",
      status: "connected",
      connection_id: "conn-gmail-1",
      connected_account: "workflow.agent@gmail.com",
      config_method: "custom_credentials",
      is_default: true,
      has_credentials: true,
      has_access_token: true,
      client_id_preview: "123456...apps",
      last_verified_at: new Date().toISOString(),
      supported_methods: ["custom_credentials", "oauth"],
      platform_oauth_available: false,
      services: ["gmail"],
      callback_url: "http://localhost:8000/api/v1/integrations/google/callback",
    },
    {
      id: "sheets",
      name: "Google Sheets",
      category: "Spreadsheets & Data",
      icon: "sheet",
      description: "Read tabular records, append lead or execution rows, and update spreadsheet cells.",
      status: "authorization_required",
      connection_id: "conn-sheets-1",
      connected_account: null,
      config_method: "custom_credentials",
      is_default: true,
      has_credentials: true,
      has_access_token: false,
      client_id_preview: "123456...apps",
      last_verified_at: null,
      supported_methods: ["custom_credentials"],
      platform_oauth_available: false,
      services: ["sheets"],
      callback_url: "http://localhost:8000/api/v1/integrations/google/callback",
    },
    {
      id: "slack",
      name: "Slack",
      category: "Team Collaboration",
      icon: "slack",
      description: "Send channel alerts, direct team messages, and automation run status updates.",
      status: "not_configured",
      connection_id: null,
      connected_account: null,
      config_method: null,
      is_default: true,
      has_credentials: false,
      has_access_token: false,
      client_id_preview: null,
      last_verified_at: null,
      supported_methods: ["custom_credentials"],
      platform_oauth_available: false,
      services: ["slack"],
      callback_url: "http://localhost:8000/api/v1/integrations/slack/callback",
    },
    {
      id: "whatsapp",
      name: "WhatsApp Business",
      category: "Customer Messaging",
      icon: "message-circle",
      description: "Send direct text notifications and pre-approved marketing/utility templates via Meta Cloud API.",
      status: "connected",
      connection_id: "conn-wa-1",
      connected_account: "FlowPilot Support (+1 555 0199)",
      config_method: "custom_credentials",
      is_default: true,
      has_credentials: true,
      has_access_token: true,
      client_id_preview: "104829...2345",
      last_verified_at: new Date().toISOString(),
      supported_methods: ["custom_credentials"],
      platform_oauth_available: false,
      services: ["whatsapp"],
      callback_url: "http://localhost:8000/api/v1/webhooks/whatsapp",
    },
  ];

  it("renders App Connections heading and all 4 provider cards", async () => {
    (api.connections.getOverview as any).mockResolvedValueOnce(mockOverview);

    renderWithClient(<AppConnectionsPage />);

    expect(await screen.findByText("App Connections")).toBeInTheDocument();
    expect(
      screen.getByText("Connect, configure, and manage the external services used by your workflows.")
    ).toBeInTheDocument();

    // Verify all 4 providers are displayed
    expect(await screen.findByText("Gmail")).toBeInTheDocument();
    expect(screen.getByText("Google Sheets")).toBeInTheDocument();
    expect(screen.getByText("Slack")).toBeInTheDocument();
    expect(screen.getByText("WhatsApp Business")).toBeInTheDocument();

    // Verify status badges
    expect(screen.getByText("Authorization Required")).toBeInTheDocument();
    expect(screen.getByText("Not Configured")).toBeInTheDocument();
  });

  it("displays connected account identifiers accurately", async () => {
    (api.connections.getOverview as any).mockResolvedValueOnce(mockOverview);

    renderWithClient(<AppConnectionsPage />);

    expect(await screen.findByText("workflow.agent@gmail.com")).toBeInTheDocument();
    expect(screen.getByText("FlowPilot Support (+1 555 0199)")).toBeInTheDocument();
  });

  it("opens interactive Setup Guide dialog when clicking Setup Guide button", async () => {
    (api.connections.getOverview as any).mockResolvedValueOnce(mockOverview);
    (api.connections.getSetupGuide as any).mockResolvedValueOnce({
      provider: "slack",
      name: "Slack",
      description: "Connect a Slack workspace to allow automated channel updates.",
      portal_name: "Slack API Apps Portal",
      portal_url: "https://api.slack.com/apps",
      callback_url: "http://localhost:8000/api/v1/integrations/slack/callback",
      supported_methods: ["custom_credentials"],
      required_fields: [],
      steps: [
        {
          step_number: 1,
          title: "Create a Slack App",
          instructions: "Navigate to the Slack API portal and click Create New App.",
          required_info: ["App Name"],
          portal_name: "Slack Apps",
          portal_url: "https://api.slack.com/apps",
        },
      ],
    });

    renderWithClient(<AppConnectionsPage />);

    const guideButtons = await screen.findAllByRole("button", { name: /Setup Guide/i });
    expect(guideButtons.length).toBeGreaterThan(0);

    // Click on Slack Setup Guide
    fireEvent.click(guideButtons[2]);

    await waitFor(() => {
      expect(screen.getByText(/Configure Slack/i)).toBeInTheDocument();
      expect(screen.getByText(/Official Developer Portal: Slack API Apps Portal/i)).toBeInTheDocument();
      expect(screen.getByText("Create a Slack App")).toBeInTheDocument();
    });
  });

  it("renders contextual link to Operational Diagnostics", async () => {
    (api.connections.getOverview as any).mockResolvedValueOnce(mockOverview);

    renderWithClient(<AppConnectionsPage />);

    const link = await screen.findByRole("link", { name: /Operational Health & Logs/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/integrations");
  });

  it("loads saved non-sensitive fields and displays masked secret indicator when opening Manage Configuration", async () => {
    const customOverview = [
      {
        ...mockOverview[2], // Slack
        client_id: "slack-client-id-9988",
        has_client_secret: true,
        has_credentials: true,
        status: "credentials_saved",
        updated_at: new Date().toISOString(),
      },
    ];
    (api.connections.getOverview as any).mockResolvedValueOnce(customOverview);

    renderWithClient(<AppConnectionsPage />);

    const manageBtn = await screen.findByRole("button", { name: /Manage Configuration/i });
    fireEvent.click(manageBtn);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Configure Slack/i })).toBeInTheDocument();
    });

    // Check that saved non-sensitive field (client_id) is populated
    const clientIdInput = screen.getByDisplayValue("slack-client-id-9988");
    expect(clientIdInput).toBeInTheDocument();

    // Check that sensitive field shows masked indicator and badge
    expect(screen.getByText("••••••••••••••••••••••••")).toBeInTheDocument();
    expect(screen.getByText(/Configured & Encrypted/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Replace Secret/i })).toBeInTheDocument();

    // Button should be in saved state
    expect(screen.getByRole("button", { name: /Credentials Saved/i })).toBeInTheDocument();
  });

  it("switches to 'Save Changes' and displays 'Unsaved Changes' badge when user edits a field", async () => {
    const customOverview = [
      {
        ...mockOverview[2],
        client_id: "slack-client-id-9988",
        has_client_secret: true,
        has_credentials: true,
        status: "credentials_saved",
        updated_at: new Date().toISOString(),
      },
    ];
    (api.connections.getOverview as any).mockResolvedValueOnce(customOverview);

    renderWithClient(<AppConnectionsPage />);

    const manageBtn = await screen.findByRole("button", { name: /Manage Configuration/i });
    fireEvent.click(manageBtn);

    await waitFor(() => {
      expect(screen.getByDisplayValue("slack-client-id-9988")).toBeInTheDocument();
    });

    // Modify the client ID
    const clientIdInput = screen.getByDisplayValue("slack-client-id-9988");
    fireEvent.change(clientIdInput, { target: { value: "slack-client-id-MODIFIED" } });

    // Expect 'Unsaved Changes' badge to appear
    await waitFor(() => {
      expect(screen.getByText("Unsaved Changes")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Save Changes/i })).toBeInTheDocument();
    });
  });

  it("reveals empty input and cancellation option when Replace Secret is clicked", async () => {
    const customOverview = [
      {
        ...mockOverview[2],
        client_id: "slack-client-id-9988",
        has_client_secret: true,
        has_credentials: true,
        status: "credentials_saved",
        updated_at: new Date().toISOString(),
      },
    ];
    (api.connections.getOverview as any).mockResolvedValueOnce(customOverview);

    renderWithClient(<AppConnectionsPage />);

    const manageBtn = await screen.findByRole("button", { name: /Manage Configuration/i });
    fireEvent.click(manageBtn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Replace Secret/i })).toBeInTheDocument();
    });

    // Click Replace Secret
    fireEvent.click(screen.getByRole("button", { name: /Replace Secret/i }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Enter new replacement secret/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Cancel replacement/i })).toBeInTheDocument();
      expect(screen.getByText(/Leave blank or cancel to keep your existing encrypted secret/i)).toBeInTheDocument();
    });
  });
});
