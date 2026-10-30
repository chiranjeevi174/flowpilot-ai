import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LLMSettingsPage from "@/app/(dashboard)/settings/llm/page";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    llm: {
      listCredentials: vi.fn(),
      discoverModels: vi.fn(),
      createCredential: vi.fn(),
      deleteCredential: vi.fn(),
      testCredential: vi.fn(),
      setPreference: vi.fn(),
      getPreference: vi.fn(),
      getUsageHistory: vi.fn(),
    },
  },
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("Multi-LLM (BYOK) Page — Collapsible Models & Audit History", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.llm.getPreference as any).mockResolvedValue(null);
  });

  const mockCredentials = [
    {
      id: "cred-1",
      user_id: "user-1",
      provider: "gemini",
      key_fingerprint: "AIzaSyD...",
      is_default: true,
      default_model: "gemini-2.5-flash",
      created_at: new Date().toISOString(),
      last_validated_at: new Date().toISOString(),
    },
  ];

  const mockModels = [
    {
      id: "gemini-2.5-flash",
      name: "Gemini 2.5 Flash",
      description: "Fast multi-modal enterprise reasoning",
      context_length: 1000000,
      supports_tools: true,
      supports_vision: true,
      pricing: { input_cost_per_1k: 0.0001, output_cost_per_1k: 0.0004 },
    },
    {
      id: "gemini-2.5-pro",
      name: "Gemini 2.5 Pro",
      description: "High intelligence flagship model",
      context_length: 2000000,
      supports_tools: true,
      supports_vision: true,
      pricing: { input_cost_per_1k: 0.00125, output_cost_per_1k: 0.005 },
    },
  ];

  const mockUsageRecords = [
    {
      id: "usage-1",
      user_id: "user-1",
      provider: "gemini",
      model_id: "gemini-2.5-flash",
      input_tokens: 1250,
      output_tokens: 420,
      total_tokens: 1670,
      latency_ms: 840,
      estimated_cost: "0.0003",
      status: "success",
      created_at: new Date().toISOString(),
    },
    {
      id: "usage-2",
      user_id: "user-1",
      provider: "openai",
      model_id: "gpt-4o",
      input_tokens: 2500,
      output_tokens: 890,
      total_tokens: 3390,
      latency_ms: 1230,
      estimated_cost: "0.0150",
      status: "success",
      created_at: new Date().toISOString(),
    },
  ];

  it("is COLLAPSED BY DEFAULT for Available Models on initial page load", async () => {
    (api.llm.listCredentials as any).mockResolvedValue(mockCredentials);
    (api.llm.discoverModels as any).mockResolvedValue(mockModels);
    (api.llm.getUsageHistory as any).mockResolvedValue(mockUsageRecords);

    renderWithClient(<LLMSettingsPage />);

    const sectionHeader = await screen.findByRole("button", {
      name: /Available Models & Default Preference/i,
    });
    expect(sectionHeader).toBeInTheDocument();
    expect(sectionHeader).toHaveAttribute("aria-expanded", "false");

    expect(
      screen.getByText("Click to expand model inventory and default preferences.")
    ).toBeInTheDocument();

    expect(document.getElementById("models-inventory-section")).toBeNull();
    expect(screen.queryByText("Fast multi-modal enterprise reasoning")).toBeNull();
  });

  it("is COLLAPSED BY DEFAULT for Recent LLM Generation Audit History on initial page load", async () => {
    (api.llm.listCredentials as any).mockResolvedValue(mockCredentials);
    (api.llm.discoverModels as any).mockResolvedValue(mockModels);
    (api.llm.getUsageHistory as any).mockResolvedValue(mockUsageRecords);

    renderWithClient(<LLMSettingsPage />);

    const auditHeader = await screen.findByRole("button", {
      name: /Recent LLM Generation Audit History/i,
    });
    expect(auditHeader).toBeInTheDocument();
    expect(auditHeader).toHaveAttribute("aria-expanded", "false");

    expect(
      screen.getByText("Click to expand audit trail and generation telemetry.")
    ).toBeInTheDocument();

    // Audit section container should not be present initially
    expect(document.getElementById("audit-history-section")).toBeNull();
  });

  it("expands Available Models when clicked without expanding Audit History (independent state)", async () => {
    (api.llm.listCredentials as any).mockResolvedValue(mockCredentials);
    (api.llm.discoverModels as any).mockResolvedValue(mockModels);
    (api.llm.getUsageHistory as any).mockResolvedValue(mockUsageRecords);

    renderWithClient(<LLMSettingsPage />);

    const modelsHeader = await screen.findByRole("button", {
      name: /Available Models & Default Preference/i,
    });
    const auditHeader = await screen.findByRole("button", {
      name: /Recent LLM Generation Audit History/i,
    });

    // Expand Models
    fireEvent.click(modelsHeader);

    // Models should be expanded, but Audit History remains collapsed
    expect(modelsHeader).toHaveAttribute("aria-expanded", "true");
    expect(auditHeader).toHaveAttribute("aria-expanded", "false");

    await waitFor(() => {
      expect(document.getElementById("models-inventory-section")).toBeInTheDocument();
      expect(screen.getByText("Gemini 2.5 Flash")).toBeInTheDocument();
    });
    expect(document.getElementById("audit-history-section")).toBeNull();
  });

  it("expands and collapses Recent LLM Generation Audit History independently, preserving telemetry data", async () => {
    (api.llm.listCredentials as any).mockResolvedValue(mockCredentials);
    (api.llm.discoverModels as any).mockResolvedValue(mockModels);
    (api.llm.getUsageHistory as any).mockResolvedValue(mockUsageRecords);

    renderWithClient(<LLMSettingsPage />);

    const modelsHeader = await screen.findByRole("button", {
      name: /Available Models & Default Preference/i,
    });
    const auditHeader = await screen.findByRole("button", {
      name: /Recent LLM Generation Audit History/i,
    });

    // Both start collapsed
    expect(modelsHeader).toHaveAttribute("aria-expanded", "false");
    expect(auditHeader).toHaveAttribute("aria-expanded", "false");

    // Click Audit History to expand
    fireEvent.click(auditHeader);
    expect(auditHeader).toHaveAttribute("aria-expanded", "true");
    expect(modelsHeader).toHaveAttribute("aria-expanded", "false");

    // Verify audit table data is displayed
    await waitFor(() => {
      expect(document.getElementById("audit-history-section")).toBeInTheDocument();
      expect(screen.getByText("Tokens (In / Out / Total)")).toBeInTheDocument();
      expect(screen.getByText("840 ms")).toBeInTheDocument();
      expect(screen.getByText("1230 ms")).toBeInTheDocument();
    });

    // Click again to collapse
    fireEvent.click(auditHeader);
    expect(auditHeader).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("audit-history-section")).toBeNull();
  });

  it("supports keyboard expansion with Enter and Space for Audit History", async () => {
    (api.llm.listCredentials as any).mockResolvedValue(mockCredentials);
    (api.llm.discoverModels as any).mockResolvedValue(mockModels);
    (api.llm.getUsageHistory as any).mockResolvedValue(mockUsageRecords);

    renderWithClient(<LLMSettingsPage />);

    const auditHeader = await screen.findByRole("button", {
      name: /Recent LLM Generation Audit History/i,
    });

    // Press Enter to expand
    fireEvent.keyDown(auditHeader, { key: "Enter" });
    expect(auditHeader).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("audit-history-section")).toBeInTheDocument();

    // Press Space to collapse
    fireEvent.keyDown(auditHeader, { key: " " });
    expect(auditHeader).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("audit-history-section")).toBeNull();
  });

  it("renders 'Set as Default' button with corrected geometry and handles click", async () => {
    (api.llm.listCredentials as any).mockResolvedValue(mockCredentials);
    (api.llm.discoverModels as any).mockResolvedValue(mockModels);
    (api.llm.getUsageHistory as any).mockResolvedValue(mockUsageRecords);
    (api.llm.setPreference as any).mockResolvedValue({
      status: "success",
      provider: "gemini",
      model_id: "gemini-2.5-flash",
    });

    renderWithClient(<LLMSettingsPage />);

    const sectionHeader = await screen.findByRole("button", {
      name: /Available Models & Default Preference/i,
    });
    fireEvent.click(sectionHeader);

    await waitFor(() => {
      expect(screen.getByText("Gemini 2.5 Pro")).toBeInTheDocument();
    });

    // Find the "Set as Default" button for non-default models
    const setDefaultButtons = screen.getAllByRole("button", { name: /Set as Default/i });
    expect(setDefaultButtons.length).toBeGreaterThan(0);
    const setDefaultBtn = setDefaultButtons[0];
    expect(setDefaultBtn).toBeInTheDocument();

    // Verify it uses the compact enterprise geometry classes
    expect(setDefaultBtn.className).toContain("h-7");
    expect(setDefaultBtn.className).toContain("leading-none");

    // Click to update default
    fireEvent.click(setDefaultBtn);

    await waitFor(() => {
      expect(api.llm.setPreference).toHaveBeenCalledWith({
        credential_id: "cred-1",
        model_id: "gemini-2.5-flash",
      });
    });
  });
});
