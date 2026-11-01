import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import IntegrationsPage from "@/app/(dashboard)/integrations/page";
import AppConnectionsPage from "@/app/(dashboard)/settings/connections/page";
import { api } from "@/lib/api/client";
import {
  findServiceConnection,
  resolveServiceStatus,
  invalidateAllIntegrationQueries,
  INTEGRATION_STATUS_MAP,
} from "@/lib/integrations-status";
import type { IntegrationConnection } from "@/types";

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
      getWhatsAppStatus: vi.fn(),
      testWhatsApp: vi.fn(),
    },
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

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
      },
    },
  });
}

function renderWithClient(ui: React.ReactElement, client = createTestQueryClient()) {
  return {
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
    queryClient: client,
  };
}

describe("Integration Status Consistency & Contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Single Source of Truth & Service Connection Matcher", () => {
    it("correctly identifies Google Sheets connection even if service attribute is 'gmail' but includes spreadsheet scope", () => {
      const connections: IntegrationConnection[] = [
        {
          id: "google-conn-123",
          user_id: "user-alpha",
          provider: "google",
          service: "gmail",
          external_account_id: "google-acc-123",
          external_account_name: "test@flowpilot.ai",
          granted_scopes: [
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/spreadsheets",
            "openid",
          ],
          token_expires_at: null,
          status: "active",
          last_verified_at: new Date().toISOString(),
          metadata_json: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ];

      const sheetsMatch = findServiceConnection(connections, "google", "sheets");
      expect(sheetsMatch).toBeDefined();
      expect(sheetsMatch?.id).toBe("google-conn-123");

      const gmailMatch = findServiceConnection(connections, "google", "gmail");
      expect(gmailMatch).toBeDefined();
      expect(gmailMatch?.id).toBe("google-conn-123");
    });

    it("does not match Sheets if Google connection only contains mail scopes", () => {
      const connections: IntegrationConnection[] = [
        {
          id: "google-mail-only",
          user_id: "user-alpha",
          provider: "google",
          service: "gmail",
          external_account_id: "google-acc-mail",
          external_account_name: "mailonly@flowpilot.ai",
          granted_scopes: ["https://www.googleapis.com/auth/gmail.send"],
          token_expires_at: null,
          status: "active",
          last_verified_at: new Date().toISOString(),
          metadata_json: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ];

      const sheetsMatch = findServiceConnection(connections, "google", "sheets");
      expect(sheetsMatch).toBeUndefined();

      const gmailMatch = findServiceConnection(connections, "google", "gmail");
      expect(gmailMatch).toBeDefined();
    });

    it("distinguishes provider configuration from user connection state", () => {
      // Global provider is configured, but user has no connection
      const statusNoConn = resolveServiceStatus(undefined, true);
      expect(statusNoConn.statusKey).toBe("not_connected");
      expect(statusNoConn.label).toBe("Not Connected");

      // Global provider is not configured, and user has no connection
      const statusNotConfigured = resolveServiceStatus(undefined, false);
      expect(statusNotConfigured.statusKey).toBe("not_configured");
      expect(statusNotConfigured.label).toBe("Not Configured");

      // User connection exists with error status
      const connError: IntegrationConnection = {
        id: "conn-err-1",
        user_id: "user-alpha",
        provider: "whatsapp",
        service: "whatsapp",
        external_account_id: "wa-101",
        external_account_name: "+15550199",
        granted_scopes: [],
        token_expires_at: null,
        status: "error",
        last_verified_at: null,
        metadata_json: {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      const statusErr = resolveServiceStatus(connError, true);
      expect(statusErr.statusKey).toBe("error");
      expect(statusErr.label).toBe("Connection Error");
    });
  });

  describe("Consistent Status Rendering on Integrations Page", () => {
    it("renders Google Sheets as Connected and Gmail as Authorization Required when connection lacks gmail.send", async () => {
      (api.integrations.listProviders as any).mockResolvedValue([
        { id: "google", name: "Google", is_configured: true, supported_services: ["gmail", "sheets"], supported_scopes: [] },
        { id: "slack", name: "Slack", is_configured: true, supported_services: ["chat"], supported_scopes: [] },
      ]);
      (api.integrations.listConnections as any).mockResolvedValue([
        {
          id: "conn-google-dual",
          user_id: "user-alpha",
          provider: "google",
          service: "gmail",
          external_account_name: "operator@flowpilot.ai",
          granted_scopes: [
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/spreadsheets",
            "openid",
          ],
          status: "active",
          last_verified_at: new Date().toISOString(),
          metadata_json: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]);
      (api.integrations.listActions as any).mockResolvedValue([]);
      (api.integrations.getWhatsAppStatus as any).mockResolvedValue({ is_configured: false });

      renderWithClient(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Google Sheets")).toBeInTheDocument();
      });

      // Google Sheets is Connected, but Gmail has Authorization Required
      expect(screen.getAllByText("Authorization Required").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole("button", { name: /Grant Gmail Permission/i })).toBeInTheDocument();
      expect(screen.getAllByText("Connected").length).toBeGreaterThanOrEqual(1);
    });

    it("renders both Google Sheets and Gmail as Connected when connection has both scopes", async () => {
      (api.integrations.listProviders as any).mockResolvedValue([
        { id: "google", name: "Google", is_configured: true, supported_services: ["gmail", "sheets"], supported_scopes: [] },
      ]);
      (api.integrations.listConnections as any).mockResolvedValue([
        {
          id: "conn-google-full",
          user_id: "user-alpha",
          provider: "google",
          service: "gmail",
          external_account_name: "operator@flowpilot.ai",
          granted_scopes: [
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/gmail.send",
            "openid",
          ],
          status: "active",
          last_verified_at: new Date().toISOString(),
          metadata_json: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]);
      (api.integrations.listActions as any).mockResolvedValue([]);
      (api.integrations.getWhatsAppStatus as any).mockResolvedValue({ is_configured: false });

      renderWithClient(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByText("Google Sheets")).toBeInTheDocument();
      });

      const connectedBadges = screen.getAllByText("Connected");
      expect(connectedBadges.length).toBeGreaterThanOrEqual(2);
    });

    it("displays Connection Error when a user connection has error status", async () => {
      (api.integrations.listProviders as any).mockResolvedValue([
        { id: "google", is_configured: true, supported_services: [], supported_scopes: [] },
        { id: "whatsapp", is_configured: true, supported_services: ["whatsapp"], supported_scopes: [] },
      ]);
      (api.integrations.listConnections as any).mockResolvedValue([
        {
          id: "conn-wa-err",
          user_id: "user-alpha",
          provider: "whatsapp",
          service: "whatsapp",
          external_account_name: "+15550199",
          status: "error",
          granted_scopes: [],
          metadata_json: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]);
      (api.integrations.listActions as any).mockResolvedValue([]);
      (api.integrations.getWhatsAppStatus as any).mockResolvedValue({ is_configured: true });

      renderWithClient(<IntegrationsPage />);

      await waitFor(() => {
        expect(screen.getByText("WhatsApp Business")).toBeInTheDocument();
        expect(screen.getByText("Connection Error")).toBeInTheDocument();
      });
    });
  });

  describe("Consistent Status Rendering on App Connections Page", () => {
    it("renders Google Sheets with Connected badge matching Integrations page", async () => {
      const mockOverview = [
        {
          id: "gmail",
          name: "Gmail",
          category: "Email Automation",
          icon: "mail",
          description: "Automate email notifications.",
          status: "connected",
          connection_id: "conn-google-dual",
          connected_account: "operator@flowpilot.ai",
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
          description: "Read tabular records and update cells.",
          status: "connected",
          connection_id: "conn-google-dual",
          connected_account: "operator@flowpilot.ai",
          config_method: "custom_credentials",
          is_default: true,
          has_credentials: true,
          has_access_token: true,
          client_id_preview: "123456...apps",
          last_verified_at: new Date().toISOString(),
          supported_methods: ["custom_credentials"],
          platform_oauth_available: false,
          services: ["sheets"],
          callback_url: "http://localhost:8000/api/v1/integrations/google/callback",
        },
      ];

      (api.connections.getOverview as any).mockResolvedValue(mockOverview);

      renderWithClient(<AppConnectionsPage />);

      await waitFor(() => {
        expect(screen.getByText("Google Sheets")).toBeInTheDocument();
      });

      const connectedBadges = screen.getAllByText("Connected");
      expect(connectedBadges.length).toBe(2);
    });

    it("renders long status labels properly without crashing", async () => {
      const mockOverview = [
        {
          id: "slack",
          name: "Slack",
          category: "Team Collaboration",
          icon: "slack",
          description: "Send channel alerts.",
          status: "configuration_incomplete",
          connection_id: null,
          connected_account: null,
          config_method: null,
          is_default: false,
          has_credentials: false,
          has_access_token: false,
          client_id_preview: null,
          last_verified_at: null,
          supported_methods: ["custom_credentials"],
          platform_oauth_available: false,
          services: ["slack"],
          callback_url: "http://localhost:8000/api/v1/integrations/slack/callback",
        },
      ];

      (api.connections.getOverview as any).mockResolvedValue(mockOverview);

      renderWithClient(<AppConnectionsPage />);

      await waitFor(() => {
        expect(screen.getByText("Configuration Incomplete")).toBeInTheDocument();
      });
    });
  });

  describe("Query Cache Invalidation & Synchronization", () => {
    it("invalidates all integration and connection queries across pages", () => {
      const queryClient = createTestQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      invalidateAllIntegrationQueries(queryClient);

      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["integrations"] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["integrations", "connections"] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["app-connections-overview"] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["monitoring", "health"] });
    });
  });

  describe("Status Badge Accessibility and Visual Style Map", () => {
    it("contains icon and distinct accessible label for all supported statuses", () => {
      const statuses = [
        "connected",
        "active",
        "configured",
        "credentials_saved",
        "authorization_required",
        "configuration_incomplete",
        "not_configured",
        "not_connected",
        "token_expired",
        "error",
        "connection_error",
      ];

      for (const st of statuses) {
        const config = INTEGRATION_STATUS_MAP[st];
        expect(config).toBeDefined();
        expect(config.label).toBeTruthy();
        expect(config.icon).toBeDefined();
        expect(config.bg).toContain("bg-");
        expect(config.text).toContain("text-");
      }
    });
  });
});
