import React from "react";
import type { IntegrationConnection } from "@/types";
import {
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Unplug,
  ShieldCheck,
  KeyRound,
  Lock,
  Loader2,
} from "lucide-react";

export interface StatusStyleConfig {
  label: string;
  bg: string;
  text: string;
  border: string;
  icon: React.ComponentType<{ className?: string }>;
}

export const INTEGRATION_STATUS_MAP: Record<string, StatusStyleConfig> = {
  connected: {
    label: "Connected",
    bg: "bg-emerald-500/10 dark:bg-emerald-500/20",
    text: "text-emerald-700 dark:text-emerald-400",
    border: "border-emerald-500/20",
    icon: CheckCircle2,
  },
  active: {
    label: "Connected",
    bg: "bg-emerald-500/10 dark:bg-emerald-500/20",
    text: "text-emerald-700 dark:text-emerald-400",
    border: "border-emerald-500/20",
    icon: CheckCircle2,
  },
  credentials_saved: {
    label: "Credentials Saved",
    bg: "bg-teal-500/10 dark:bg-teal-500/20",
    text: "text-teal-700 dark:text-teal-400",
    border: "border-teal-500/20",
    icon: ShieldCheck,
  },
  configured: {
    label: "Configured",
    bg: "bg-teal-500/10 dark:bg-teal-500/20",
    text: "text-teal-700 dark:text-teal-400",
    border: "border-teal-500/20",
    icon: ShieldCheck,
  },
  authorization_required: {
    label: "Authorization Required",
    bg: "bg-blue-500/10 dark:bg-blue-500/20",
    text: "text-blue-700 dark:text-blue-400",
    border: "border-blue-500/20",
    icon: KeyRound,
  },
  configuration_incomplete: {
    label: "Configuration Incomplete",
    bg: "bg-amber-500/10 dark:bg-amber-500/20",
    text: "text-amber-700 dark:text-amber-400",
    border: "border-amber-500/20",
    icon: AlertTriangle,
  },
  not_configured: {
    label: "Not Configured",
    bg: "bg-slate-500/10 dark:bg-slate-500/20",
    text: "text-slate-600 dark:text-slate-400",
    border: "border-slate-500/20",
    icon: Unplug,
  },
  not_connected: {
    label: "Not Connected",
    bg: "bg-slate-500/10 dark:bg-slate-500/20",
    text: "text-slate-600 dark:text-slate-400",
    border: "border-slate-500/20",
    icon: Unplug,
  },
  token_expired: {
    label: "Token Expired",
    bg: "bg-rose-500/10 dark:bg-rose-500/20",
    text: "text-rose-700 dark:text-rose-400",
    border: "border-rose-500/20",
    icon: AlertCircle,
  },
  expired: {
    label: "Token Expired",
    bg: "bg-rose-500/10 dark:bg-rose-500/20",
    text: "text-rose-700 dark:text-rose-400",
    border: "border-rose-500/20",
    icon: AlertCircle,
  },
  error: {
    label: "Connection Error",
    bg: "bg-red-500/10 dark:bg-red-500/20",
    text: "text-red-700 dark:text-red-400",
    border: "border-red-500/20",
    icon: AlertCircle,
  },
  connection_error: {
    label: "Connection Error",
    bg: "bg-red-500/10 dark:bg-red-500/20",
    text: "text-red-700 dark:text-red-400",
    border: "border-red-500/20",
    icon: AlertCircle,
  },
  restricted: {
    label: "Restricted by Provider",
    bg: "bg-purple-500/10 dark:bg-purple-500/20",
    text: "text-purple-700 dark:text-purple-400",
    border: "border-purple-500/20",
    icon: Lock,
  },
  verifying: {
    label: "Verifying...",
    bg: "bg-teal-500/10 dark:bg-teal-500/20",
    text: "text-teal-700 dark:text-teal-400",
    border: "border-teal-500/20",
    icon: Loader2,
  },
};

/**
 * Locate a user's active/relevant connection for a specific provider and sub-service.
 * Handles unified Google OAuth accounts that grant both Gmail and Sheets scopes.
 */
export function findServiceConnection(
  connections: IntegrationConnection[],
  providerId: string,
  service?: string
): IntegrationConnection | undefined {
  const normProvider = providerId.toLowerCase().trim();
  const normService = service?.toLowerCase().trim();

  // 1. Direct match on provider and service
  if (normService) {
    const directMatch = connections.find(
      (c) =>
        c.provider.toLowerCase() === normProvider &&
        c.service?.toLowerCase() === normService
    );
    if (directMatch) return directMatch;
  }

  // 2. Google-specific resolution:
  // In Google OAuth, a connection might be registered under provider "google" with
  // granted_scopes covering spreadsheets, gmail, or both.
  if (normProvider === "google") {
    if (normService === "sheets") {
      const sheetsConn = connections.find(
        (c) =>
          c.provider.toLowerCase() === "google" &&
          (c.service?.toLowerCase() === "sheets" ||
            c.granted_scopes?.some((s) => s.toLowerCase().includes("spreadsheets")))
      );
      if (sheetsConn) return sheetsConn;
      // Do not fall back to mail-only connections for Google Sheets
      return undefined;
    } else if (normService === "gmail") {
      const gmailConn = connections.find(
        (c) =>
          c.provider.toLowerCase() === "google" &&
          (c.service?.toLowerCase() === "gmail" ||
            c.granted_scopes?.some(
              (s) => s.toLowerCase().includes("mail") || s.toLowerCase().includes("gmail")
            ) ||
            !c.service)
      );
      if (gmailConn) return gmailConn;
      return undefined;
    }
  }

  // 3. Fallback: match by provider, prioritizing default connections
  const providerMatches = connections.filter(
    (c) => c.provider.toLowerCase() === normProvider
  );
  if (providerMatches.length > 0) {
    return providerMatches.find((c) => c.is_default) || providerMatches[0];
  }

  return undefined;
}

/**
 * Resolve connection operational status into standardized label, icon, and styling.
 */
export function resolveServiceStatus(
  conn: IntegrationConnection | undefined,
  isProviderConfigured: boolean = true,
  service?: string
): {
  statusKey: string;
  label: string;
  isConnected: boolean;
  isError: boolean;
  config: StatusStyleConfig;
} {
  let statusKey = "not_configured";

  if (!conn) {
    statusKey = isProviderConfigured ? "not_connected" : "not_configured";
  } else {
    const rawStatus = String(conn.status || "").toLowerCase().trim();
    const normProvider = conn.provider?.toLowerCase().trim();
    const normService = (service || conn.service || "").toLowerCase().trim();

    // Specific capability readiness: Google OAuth requires specific scopes
    if (normProvider === "google") {
      if (normService === "gmail") {
        const hasGmailSend = conn.granted_scopes?.some(
          (s) =>
            s.toLowerCase().includes("gmail.send") ||
            s.toLowerCase().includes("mail.google.com")
        );
        if (!hasGmailSend) {
          statusKey = "authorization_required";
          const config =
            INTEGRATION_STATUS_MAP[statusKey] || INTEGRATION_STATUS_MAP.authorization_required;
          return {
            statusKey,
            label: config.label,
            isConnected: false,
            isError: false,
            config,
          };
        }
      } else if (normService === "sheets") {
        const hasSheets = conn.granted_scopes?.some((s) =>
          s.toLowerCase().includes("spreadsheets")
        );
        if (!hasSheets) {
          statusKey = "authorization_required";
          const config =
            INTEGRATION_STATUS_MAP[statusKey] || INTEGRATION_STATUS_MAP.authorization_required;
          return {
            statusKey,
            label: config.label,
            isConnected: false,
            isError: false,
            config,
          };
        }
      }
    }

    if (rawStatus === "active") {
      statusKey = "connected";
    } else if (rawStatus === "error") {
      statusKey = "error";
    } else if (rawStatus === "expired" || rawStatus === "token_expired") {
      statusKey = "token_expired";
    } else if (rawStatus === "authorization_required") {
      statusKey = "authorization_required";
    } else if (rawStatus === "configured" || rawStatus === "credentials_saved") {
      statusKey = "credentials_saved";
    } else if (rawStatus === "restricted") {
      statusKey = "restricted";
    } else {
      statusKey = rawStatus || "not_configured";
    }
  }

  const config =
    INTEGRATION_STATUS_MAP[statusKey] || INTEGRATION_STATUS_MAP.not_configured;

  return {
    statusKey,
    label: config.label,
    isConnected: statusKey === "connected",
    isError: statusKey === "error" || statusKey === "token_expired",
    config,
  };
}

/**
 * Invalidate all integration-related TanStack queries to maintain cache synchronization
 * across External Integrations, App Connections, and Health Monitoring.
 */
export function invalidateAllIntegrationQueries(queryClient: {
  invalidateQueries: (options: { queryKey: any[] }) => Promise<unknown> | void;
}) {
  queryClient.invalidateQueries({ queryKey: ["integrations"] });
  queryClient.invalidateQueries({ queryKey: ["integrations", "connections"] });
  queryClient.invalidateQueries({ queryKey: ["integrations", "providers"] });
  queryClient.invalidateQueries({ queryKey: ["integrations", "whatsapp-status"] });
  queryClient.invalidateQueries({ queryKey: ["app-connections-overview"] });
  queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
}
