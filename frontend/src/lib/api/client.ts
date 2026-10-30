import type {
  AgentRun,
  AgentRunListResponse,
  AgentEvent,
  ExternalAction,
  IntegrationConnection,
  IntegrationProvider,
  WhatsAppStatus,
  LLMCredential,
  LLMModelInfo,
  LLMPreference,
  LLMProvider,
  LLMUsageRecord,
  MonitoringHealth,
  ScheduledWorkflow,
  AppNotification,
  User,
  AppConnectionOverviewItem,
  ProviderSetupGuideResponse,
  SaveCustomCredentialsRequest,
} from "@/types";

export class ApiError extends Error {
  status: number;
  data: any;

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

interface FetcherOptions extends RequestInit {
  timeoutMs?: number;
}

async function fetcher<T>(url: string, options: FetcherOptions = {}): Promise<T> {
  const { timeoutMs = 30000, signal: callerSignal, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort(new Error("Request timeout"));
  }, timeoutMs);

  if (callerSignal) {
    if (callerSignal.aborted) {
      clearTimeout(timeoutId);
      controller.abort(callerSignal.reason);
    } else {
      callerSignal.addEventListener("abort", () => {
        clearTimeout(timeoutId);
        controller.abort(callerSignal.reason);
      });
    }
  }

  const headers = new Headers(fetchOptions.headers || {});
  if (!headers.has("Content-Type") && fetchOptions.body && typeof fetchOptions.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  try {
    const res = await fetch(url, {
      ...fetchOptions,
      headers,
      signal: controller.signal,
    });

    if (res.status === 204) {
      return {} as T;
    }

    const contentType = res.headers.get("content-type") || "";
    let data: any;
    if (contentType.includes("application/json")) {
      data = await res.json();
    } else {
      data = await res.text();
    }

    if (!res.ok) {
      const errorMsg = data?.detail || data?.error || res.statusText || "Request failed";
      throw new ApiError(errorMsg, res.status, data);
    }

    return data as T;
  } catch (error: any) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error?.name === "AbortError" || controller.signal.aborted) {
      throw new ApiError(
        "Request timed out while waiting for server response. Please verify execution history before retrying.",
        408
      );
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

export const api = {
  auth: {
    login: (body: { email: string; password: string }) =>
      fetcher<{ success: boolean }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    register: (body: { email: string; password: string; full_name?: string }) =>
      fetcher<User>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    logout: () =>
      fetcher<{ success: boolean }>("/api/auth/logout", {
        method: "POST",
      }),
    me: () => fetcher<{ user: User }>("/api/auth/me"),
    updateProfile: (body: { full_name?: string; password?: string }) =>
      fetcher<User>("/api/proxy/users/me", {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    forgotPassword: (body: { email: string }) =>
      fetcher<{ message: string; email_sent: boolean; dev_reset_url?: string }>(
        "/api/auth/forgot-password",
        {
          method: "POST",
          body: JSON.stringify(body),
        }
      ),
    validateResetToken: (token: string) =>
      fetcher<{ valid: boolean; email?: string; reason?: string }>(
        `/api/auth/reset-password/validate?token=${encodeURIComponent(token)}`
      ),
    resetPassword: (body: { token: string; password: string }) =>
      fetcher<{ message: string }>("/api/auth/reset-password", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  monitoring: {
    getHealth: () => fetcher<MonitoringHealth>("/api/proxy/monitoring/health"),
  },

  workflows: {
    createRun: (body: { request: string; provider?: string; model?: string }) =>
      fetcher<AgentRun>("/api/proxy/agents/runs", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    listRuns: (params?: { limit?: number; offset?: number; status?: string }) => {
      const sp = new URLSearchParams();
      if (params?.limit) sp.set("limit", params.limit.toString());
      if (params?.offset) sp.set("offset", params.offset.toString());
      if (params?.status) sp.set("status", params.status);
      const qs = sp.toString();
      return fetcher<AgentRunListResponse>(`/api/proxy/agents/runs${qs ? `?${qs}` : ""}`);
    },
    getRun: (id: string) => fetcher<AgentRun>(`/api/proxy/agents/runs/${id}`),
    getRunEvents: (id: string) => fetcher<AgentEvent[]>(`/api/proxy/agents/runs/${id}/events`),
    cancelRun: (id: string) =>
      fetcher<AgentRun>(`/api/proxy/agents/runs/${id}/cancel`, {
        method: "POST",
      }),
    approveRun: (id: string, comment?: string) =>
      fetcher<AgentRun>(`/api/proxy/agents/runs/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({ comment }),
      }),
    rejectRun: (id: string, comment?: string) =>
      fetcher<AgentRun>(`/api/proxy/agents/runs/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ comment }),
      }),
  },

  llm: {
    listProviders: () => fetcher<LLMProvider[]>("/api/proxy/llm/providers"),
    listCredentials: () => fetcher<LLMCredential[]>("/api/proxy/llm/credentials"),
    connectCredential: (body: { provider: string; api_key: string }) =>
      fetcher<LLMCredential>("/api/proxy/llm/credentials", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    testCredential: (id: string) =>
      fetcher<{ provider: string; status: string; message: string; tested_at: string }>(
        `/api/proxy/llm/credentials/${id}/test`,
        { method: "POST" }
      ),
    deleteCredential: (id: string) =>
      fetcher<void>(`/api/proxy/llm/credentials/${id}`, {
        method: "DELETE",
      }),
    getPreference: () => fetcher<LLMPreference | null>("/api/proxy/llm/preferences"),
    setPreference: (body: { credential_id: string; model_id: string }) =>
      fetcher<LLMPreference>("/api/proxy/llm/preferences", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    discoverModels: async (provider?: string): Promise<LLMModelInfo[]> => {
      const qs = provider ? `?provider=${encodeURIComponent(provider)}` : "";
      const res = await fetcher<any>(`/api/proxy/llm/models${qs}`);
      if (Array.isArray(res)) return res as LLMModelInfo[];
      if (res && Array.isArray(res.models)) return res.models as LLMModelInfo[];
      return [] as LLMModelInfo[];
    },
    getUsageHistory: (limit: number = 50) =>
      fetcher<LLMUsageRecord[]>(`/api/proxy/llm/usage?limit=${limit}`),
  },

  integrations: {
    listProviders: () => fetcher<IntegrationProvider[]>("/api/proxy/integrations/providers"),
    listConnections: () => fetcher<IntegrationConnection[]>("/api/proxy/integrations"),
    getConnection: (id: string) =>
      fetcher<IntegrationConnection>(`/api/proxy/integrations/${id}`),
    testConnection: (id: string) =>
      fetcher<{ id: string; provider: string; status: string; message: string }>(
        `/api/proxy/integrations/${id}/test`,
        { method: "POST" }
      ),
    disconnectConnection: (id: string) =>
      fetcher<void>(`/api/proxy/integrations/${id}`, {
        method: "DELETE",
      }),
    getAuthorizeUrl: (provider: string, service?: string) => {
      const sp = new URLSearchParams();
      if (service) sp.set("service", service);
      const qs = sp.toString();
      return fetcher<{ provider: string; authorization_url: string; state: string }>(
        `/api/proxy/integrations/${provider}/authorize${qs ? `?${qs}` : ""}`
      );
    },
    listActions: (limit: number = 50) =>
      fetcher<ExternalAction[]>(`/api/proxy/integrations/actions?limit=${limit}`),
    getWhatsAppStatus: () => fetcher<WhatsAppStatus>("/api/proxy/integrations/whatsapp/status"),
    testWhatsApp: () =>
      fetcher<{ id: string; provider: string; status: string; message: string; ok: boolean }>(
        "/api/proxy/integrations/whatsapp/test",
        { method: "POST" }
      ),
  },

  connections: {
    getOverview: () => fetcher<AppConnectionOverviewItem[]>("/api/proxy/integrations/overview"),
    getSetupGuides: () => fetcher<ProviderSetupGuideResponse[]>("/api/proxy/integrations/guides"),
    getSetupGuide: (provider: string) =>
      fetcher<ProviderSetupGuideResponse>(
        `/api/proxy/integrations/guides/${encodeURIComponent(provider)}`
      ),
    saveCredentials: (data: SaveCustomCredentialsRequest) =>
      fetcher<IntegrationConnection>("/api/proxy/integrations/credentials", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    setDefault: (id: string) =>
      fetcher<IntegrationConnection>(`/api/proxy/integrations/${id}/default`, {
        method: "POST",
      }),
    testConnection: (id: string) =>
      fetcher<{ id: string; provider: string; status: string; message: string; ok: boolean }>(
        `/api/proxy/integrations/${id}/test`,
        { method: "POST" }
      ),
    disconnectConnection: (id: string) =>
      fetcher<void>(`/api/proxy/integrations/${id}`, {
        method: "DELETE",
      }),
    getAuthorizeUrl: (provider: string, service?: string, connectionId?: string) => {
      const sp = new URLSearchParams();
      if (service) sp.set("service", service);
      if (connectionId) sp.set("connection_id", connectionId);
      const qs = sp.toString();
      return fetcher<{ provider: string; authorization_url: string; state: string }>(
        `/api/proxy/integrations/${provider}/authorize${qs ? `?${qs}` : ""}`
      );
    },
  },

  schedules: {
    listSchedules: async (): Promise<ScheduledWorkflow[]> => {
      const res = await fetcher<any>("/api/proxy/schedules");
      if (Array.isArray(res)) return res as ScheduledWorkflow[];
      if (res && Array.isArray(res.items)) return res.items as ScheduledWorkflow[];
      return [] as ScheduledWorkflow[];
    },
    createSchedule: (body: {
      name: string;
      workflow_request: string;
      schedule_type: string;
      timezone?: string;
      schedule_configuration: Record<string, any>;
    }) =>
      fetcher<ScheduledWorkflow>("/api/proxy/schedules", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    getSchedule: (id: string) => fetcher<ScheduledWorkflow>(`/api/proxy/schedules/${id}`),
    updateSchedule: (
      id: string,
      body: {
        name?: string;
        workflow_request?: string;
        schedule_type?: string;
        timezone?: string;
        schedule_configuration?: Record<string, any>;
      }
    ) =>
      fetcher<ScheduledWorkflow>(`/api/proxy/schedules/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    pauseSchedule: (id: string) =>
      fetcher<ScheduledWorkflow>(`/api/proxy/schedules/${id}/pause`, {
        method: "POST",
      }),
    resumeSchedule: (id: string) =>
      fetcher<ScheduledWorkflow>(`/api/proxy/schedules/${id}/resume`, {
        method: "POST",
      }),
    deleteSchedule: (id: string) =>
      fetcher<void>(`/api/proxy/schedules/${id}`, {
        method: "DELETE",
      }),
  },

  notifications: {
    listNotifications: (limit: number = 50, includeDismissed: boolean = false) => {
      const sp = new URLSearchParams();
      sp.set("limit", String(limit));
      if (includeDismissed) sp.set("include_dismissed", "true");
      return fetcher<{ items: AppNotification[]; unread_count: number; total: number }>(
        `/api/proxy/notifications?${sp.toString()}`
      );
    },
    createNotification: (body: {
      type: string;
      category?: string;
      title: string;
      message: string;
      dedup_key: string;
      link_url?: string;
      meta_data?: Record<string, any>;
    }) =>
      fetcher<AppNotification>("/api/proxy/notifications", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    markAsRead: (id: string) =>
      fetcher<AppNotification>(`/api/proxy/notifications/${id}/read`, {
        method: "PATCH",
      }),
    markAllRead: () =>
      fetcher<{ updated: number }>("/api/proxy/notifications/mark-all-read", {
        method: "POST",
      }),
    dismissNotification: (id: string) =>
      fetcher<{ dismissed: boolean }>(`/api/proxy/notifications/${id}/dismiss`, {
        method: "POST",
      }),
    deleteNotification: (id: string) =>
      fetcher<void>(`/api/proxy/notifications/${id}`, {
        method: "DELETE",
      }),
  },
};
