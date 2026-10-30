"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  FileSpreadsheet,
  Info,
  KeyRound,
  Layers,
  Lock,
  Mail,
  MessageCircle,
  MessageSquare,
  Plug,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  Unplug,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type {
  AppConnectionOverviewItem,
  AppConnectionStatus,
  SaveCustomCredentialsRequest,
} from "@/types";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

// Status configuration map for badges
const STATUS_CONFIG: Record<
  AppConnectionStatus,
  { label: string; bg: string; text: string; border: string; icon: React.ComponentType<{ className?: string }> }
> = {
  connected: {
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
  token_expired: {
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
  restricted: {
    label: "Restricted by Provider",
    bg: "bg-purple-500/10 dark:bg-purple-500/20",
    text: "text-purple-700 dark:text-purple-400",
    border: "border-purple-500/20",
    icon: Lock,
  },
};

function formatLastUpdated(dateStr?: string | null): string | null {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return null;
  }
}

export default function AppConnectionsPage() {
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  // Active configure modal state
  const [selectedProvider, setSelectedProvider] = React.useState<AppConnectionOverviewItem | null>(null);
  const [activeTab, setActiveTab] = React.useState<"guide" | "credentials">("guide");
  const [disconnectTarget, setDisconnectTarget] = React.useState<AppConnectionOverviewItem | null>(null);

  // Form states for custom credentials
  const [clientId, setClientId] = React.useState("");
  const [clientSecret, setClientSecret] = React.useState("");
  const [accessToken, setAccessToken] = React.useState("");
  const [phoneNumberId, setPhoneNumberId] = React.useState("");
  const [businessAccountId, setBusinessAccountId] = React.useState("");
  const [appSecret, setAppSecret] = React.useState("");
  const [webhookVerifyToken, setWebhookVerifyToken] = React.useState("");
  const [graphApiVersion, setGraphApiVersion] = React.useState("v21.0");

  // UX states for secrets & replacement
  const [showSecret, setShowSecret] = React.useState(false);
  const [isReplacingSecret, setIsReplacingSecret] = React.useState(false);
  const [isReplacingToken, setIsReplacingToken] = React.useState(false);
  const [justSaved, setJustSaved] = React.useState(false);
  const [copiedUrl, setCopiedUrl] = React.useState<string | null>(null);

  // Track initial values to detect unsaved changes
  const [initialValues, setInitialValues] = React.useState({
    clientId: "",
    phoneNumberId: "",
    businessAccountId: "",
    graphApiVersion: "v21.0",
  });

  // Handle OAuth callback notification banner
  React.useEffect(() => {
    const status = searchParams.get("status");
    const provider = searchParams.get("provider");
    if (status === "success" && provider) {
      toast.success(`Successfully connected ${provider.toUpperCase()}`, {
        description: "Your integration authorization has been verified and securely saved.",
      });
      queryClient.invalidateQueries({ queryKey: ["app-connections-overview"] });
    }
  }, [searchParams, queryClient]);

  // Query overview cards
  const {
    data: overview = [],
    isLoading: isOverviewLoading,
    isRefetching,
    refetch,
  } = useQuery({
    queryKey: ["app-connections-overview"],
    queryFn: () => api.connections.getOverview(),
  });

  // Query setup guide for selected provider
  const { data: setupGuide, isLoading: isGuideLoading } = useQuery({
    queryKey: ["provider-setup-guide", selectedProvider?.id],
    queryFn: () => {
      if (!selectedProvider) return null;
      const target = selectedProvider.id === "sheets" ? "google" : selectedProvider.id;
      return api.connections.getSetupGuide(target);
    },
    enabled: !!selectedProvider,
  });

  // Populate modal inputs when provider selected or updated from overview
  React.useEffect(() => {
    if (selectedProvider) {
      const initialClientId = selectedProvider.client_id || "";
      const initialPhone = selectedProvider.phone_number_id || "";
      const initialWaba = selectedProvider.business_account_id || "";
      const initialGraph = selectedProvider.graph_api_version || "v21.0";

      setClientId(initialClientId);
      setClientSecret("");
      setAccessToken("");
      setPhoneNumberId(initialPhone);
      setBusinessAccountId(initialWaba);
      setAppSecret("");
      setWebhookVerifyToken("");
      setGraphApiVersion(initialGraph);
      setShowSecret(false);
      setIsReplacingSecret(false);
      setIsReplacingToken(false);
      setJustSaved(false);

      setInitialValues({
        clientId: initialClientId,
        phoneNumberId: initialPhone,
        businessAccountId: initialWaba,
        graphApiVersion: initialGraph,
      });

      setActiveTab(selectedProvider.status === "not_configured" ? "guide" : "credentials");
    }
  }, [selectedProvider]);

  // Save Credentials Mutation
  const saveMutation = useMutation({
    mutationFn: async (payload: SaveCustomCredentialsRequest) => {
      return api.connections.saveCredentials(payload);
    },
    onSuccess: (data) => {
      setJustSaved(true);
      toast.success("Credentials saved successfully", {
        description:
          data.provider === "whatsapp"
            ? "WhatsApp sender tested and verified."
            : "Credentials encrypted. You can now complete authorization.",
      });
      queryClient.invalidateQueries({ queryKey: ["app-connections-overview"] });

      // Reset replacing states
      setIsReplacingSecret(false);
      setIsReplacingToken(false);
      setClientSecret("");
      setAccessToken("");

      // Update initial values
      setInitialValues({
        clientId,
        phoneNumberId,
        businessAccountId,
        graphApiVersion,
      });
    },
    onError: (err: any) => {
      setJustSaved(false);
      toast.error("Failed to save credentials", {
        description: err.message || "An unexpected error occurred while saving credentials.",
      });
    },
  });

  // Test Connection Mutation
  const testMutation = useMutation({
    mutationFn: async (connId: string) => {
      return api.connections.testConnection(connId);
    },
    onSuccess: (data) => {
      if (data.ok) {
        toast.success("Connection test passed", {
          description: data.message || "External service verified and operational.",
        });
      } else {
        toast.error("Connection test failed", {
          description: data.message || "Could not reach external provider API.",
        });
      }
      queryClient.invalidateQueries({ queryKey: ["app-connections-overview"] });
    },
    onError: (err: any) => {
      toast.error("Connection test error", {
        description: err.message || "Error running connectivity probe.",
      });
    },
  });

  // Disconnect Mutation
  const disconnectMutation = useMutation({
    mutationFn: async (connId: string) => {
      return api.connections.disconnectConnection(connId);
    },
    onSuccess: () => {
      toast.success("Provider disconnected", {
        description: "Local credentials safely removed. Existing workflow history is preserved.",
      });
      setDisconnectTarget(null);
      setSelectedProvider(null);
      queryClient.invalidateQueries({ queryKey: ["app-connections-overview"] });
    },
    onError: (err: any) => {
      toast.error("Failed to disconnect", {
        description: err.message || "Error revoking connection credentials.",
      });
    },
  });

  // Copy helper with feedback
  const handleCopy = (text: string, identifier: string) => {
    navigator.clipboard.writeText(text);
    setCopiedUrl(identifier);
    toast.success("Copied to clipboard", { description: text });
    setTimeout(() => setCopiedUrl(null), 2500);
  };

  // Initiate OAuth flow helper
  const handleInitiateOAuth = async (item: AppConnectionOverviewItem) => {
    try {
      const provider = item.id === "sheets" ? "google" : item.id === "gmail" ? "google" : item.id;
      const service = item.id === "gmail" ? "gmail" : item.id === "sheets" ? "sheets" : undefined;
      const authData = await api.connections.getAuthorizeUrl(
        provider,
        service,
        item.connection_id || undefined
      );
      if (authData?.authorization_url) {
        window.location.assign(authData.authorization_url);
      } else {
        toast.error("Could not generate OAuth authorization URL");
      }
    } catch (err: any) {
      toast.error("Failed to initiate OAuth flow", {
        description: err.message || "Check provider credentials or platform OAuth settings.",
      });
    }
  };

  // Save handler for credentials form
  const handleSaveCredentials = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProvider) return;

    const provider = selectedProvider.id === "sheets" ? "google" : selectedProvider.id === "gmail" ? "google" : selectedProvider.id;
    const service = selectedProvider.id;

    if (selectedProvider.id === "whatsapp") {
      saveMutation.mutate({
        provider: "whatsapp",
        service: "whatsapp",
        access_token: isReplacingToken || !selectedProvider.has_access_token ? (accessToken.trim() || undefined) : undefined,
        phone_number_id: phoneNumberId.trim() || undefined,
        business_account_id: businessAccountId.trim() || undefined,
        app_secret: appSecret.trim() || undefined,
        webhook_verify_token: webhookVerifyToken.trim() || undefined,
        graph_api_version: graphApiVersion.trim() || "v21.0",
        is_default: true,
      });
    } else {
      saveMutation.mutate({
        provider,
        service,
        client_id: clientId.trim() || undefined,
        client_secret: isReplacingSecret || !selectedProvider.has_client_secret ? (clientSecret.trim() || undefined) : undefined,
        is_default: true,
      });
    }
  };

  // Compute dirty state (unsaved changes)
  const isDirty = React.useMemo(() => {
    if (!selectedProvider) return false;
    if (selectedProvider.id === "whatsapp") {
      return (
        phoneNumberId !== initialValues.phoneNumberId ||
        businessAccountId !== initialValues.businessAccountId ||
        graphApiVersion !== initialValues.graphApiVersion ||
        (isReplacingToken && accessToken.trim().length > 0) ||
        appSecret.trim().length > 0 ||
        webhookVerifyToken.trim().length > 0
      );
    }
    return (
      clientId !== initialValues.clientId ||
      (isReplacingSecret && clientSecret.trim().length > 0)
    );
  }, [
    selectedProvider,
    clientId,
    clientSecret,
    isReplacingSecret,
    phoneNumberId,
    businessAccountId,
    graphApiVersion,
    isReplacingToken,
    accessToken,
    appSecret,
    webhookVerifyToken,
    initialValues,
  ]);

  const isConfigured = Boolean(
    selectedProvider?.has_credentials ||
    selectedProvider?.has_client_secret ||
    selectedProvider?.has_access_token ||
    selectedProvider?.connection_id
  );

  // Compute primary action button state
  const getSaveButtonState = () => {
    if (saveMutation.isPending) {
      return {
        label: "Saving...",
        icon: <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />,
        className: "bg-[#24433F] text-white opacity-80 cursor-not-allowed",
        disabled: true,
      };
    }
    if (justSaved || (!isDirty && isConfigured)) {
      return {
        label: "Credentials Saved",
        icon: <Check className="h-3.5 w-3.5 mr-1.5 text-emerald-400" />,
        className: "bg-[#1B3330] text-emerald-300 border border-emerald-500/30",
        disabled: !isDirty,
      };
    }
    if (isDirty) {
      return {
        label: "Save Changes",
        icon: <Save className="h-3.5 w-3.5 mr-1.5" />,
        className: "bg-[#087F72] hover:bg-[#06655B] text-white shadow-xs",
        disabled: false,
      };
    }
    return {
      label: "Save Credentials",
      icon: <KeyRound className="h-3.5 w-3.5 mr-1.5" />,
      className: "bg-[#24433F] hover:bg-[#1B3330] text-white",
      disabled: false,
    };
  };

  const saveBtn = getSaveButtonState();

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <PageHeader
        title="App Connections"
        description="Connect, configure, and manage the external services used by your workflows."
      >
        <div className="flex items-center gap-2">
          <Link href="/integrations" data-testid="link-integrations">
            <Button
              variant="outline"
              size="sm"
              className="border-[#E2E8E7] text-[#202B33] hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <Layers className="h-3.5 w-3.5 mr-1.5 text-[#087F72]" />
              Operational Health & Logs
              <ArrowRight className="h-3 w-3 ml-1 text-muted-foreground" />
            </Button>
          </Link>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isRefetching}
            className="border-[#E2E8E7]"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${isRefetching ? "animate-spin text-[#087F72]" : ""}`} />
            Refresh
          </Button>
        </div>
      </PageHeader>

      {/* Modern Enterprise Info Banner */}
      <div className="bg-[#FFFFFF] border border-[#E2E8E7] rounded-xl p-4 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="p-2.5 rounded-lg bg-[#087F72]/10 border border-[#087F72]/20 text-[#087F72] shrink-0 mt-0.5 sm:mt-0">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-[#202B33]">User-Isolated Secure Integration Credentials</h4>
            <p className="text-xs text-[#64748B] mt-0.5 leading-relaxed">
              Every FlowPilot AI user maintains isolated integration credentials. Your API secrets and tokens are encrypted at rest with multi-key authenticated cryptography and decrypted only within authorized execution boundaries.
            </p>
          </div>
        </div>
        <div className="shrink-0">
          <span className="text-[11px] font-medium text-[#087F72] bg-[#087F72]/10 px-2.5 py-1 rounded-md border border-[#087F72]/20">
            AES-256 MultiFernet
          </span>
        </div>
      </div>

      {/* Provider Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {isOverviewLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="border-[#E2E8E7] shadow-xs">
                <CardHeader>
                  <Skeleton className="h-6 w-32 mb-2" />
                  <Skeleton className="h-4 w-48" />
                </CardHeader>
                <CardContent className="space-y-3">
                  <Skeleton className="h-10 w-full" />
                </CardContent>
                <CardFooter>
                  <Skeleton className="h-9 w-28" />
                </CardFooter>
              </Card>
            ))
          : overview.map((item) => {
              const statusCfg = STATUS_CONFIG[item.status as AppConnectionStatus] || STATUS_CONFIG.not_configured;
              const StatusIcon = statusCfg.icon;

              return (
                <Card
                  key={item.id}
                  className="bg-[#FFFFFF] border-[#E2E8E7] shadow-xs hover:border-[#087F72]/40 transition-all flex flex-col justify-between"
                >
                  <CardHeader className="pb-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div
                          className={`h-11 w-11 rounded-lg flex items-center justify-center shrink-0 border ${
                            item.id === "gmail"
                              ? "bg-red-50 text-red-600 border-red-200"
                              : item.id === "sheets"
                              ? "bg-emerald-50 text-emerald-600 border-emerald-200"
                              : item.id === "slack"
                              ? "bg-purple-50 text-purple-600 border-purple-200"
                              : "bg-teal-50 text-teal-600 border-teal-200"
                          }`}
                        >
                          {item.id === "gmail" && <Mail className="h-5 w-5" />}
                          {item.id === "sheets" && <FileSpreadsheet className="h-5 w-5" />}
                          {item.id === "slack" && <MessageSquare className="h-5 w-5" />}
                          {item.id === "whatsapp" && <MessageCircle className="h-5 w-5" />}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <CardTitle className="text-base font-bold text-[#202B33]">
                              {item.name}
                            </CardTitle>
                            {item.is_default && item.connection_id && (
                              <Badge variant="outline" className="text-[10px] bg-slate-100 text-slate-700 border-slate-300">
                                Default
                              </Badge>
                            )}
                          </div>
                          <span className="text-[11px] text-[#64748B] font-medium block">
                            {item.category}
                          </span>
                        </div>
                      </div>

                      {/* Status Badge */}
                      <Badge
                        variant="outline"
                        className={`text-xs px-2.5 py-0.5 font-medium flex items-center gap-1.5 ${statusCfg.bg} ${statusCfg.text} ${statusCfg.border}`}
                      >
                        <StatusIcon className="h-3 w-3" />
                        {statusCfg.label}
                      </Badge>
                    </div>

                    <CardDescription className="text-xs text-[#64748B] pt-2 line-clamp-2">
                      {item.description}
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="py-2.5 space-y-2.5">
                    {/* Connection details box */}
                    <div className="bg-[#F7F8F6] rounded-lg p-2.5 border border-[#E2E8E7] text-xs space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[#64748B]">Connected Entity:</span>
                        <span className="font-semibold text-[#202B33] font-mono text-[11px] truncate max-w-[200px]">
                          {item.connected_account || (item.has_credentials ? "Configured (Awaiting Auth)" : "None")}
                        </span>
                      </div>

                      <div className="flex items-center justify-between">
                        <span className="text-[#64748B]">Supported Connection:</span>
                        <div className="flex items-center gap-1.5">
                          {item.supported_methods.includes("custom_credentials") && (
                            <span className="text-[10px] bg-white border border-[#E2E8E7] px-1.5 py-0.5 rounded text-[#202B33]">
                              Custom Credentials
                            </span>
                          )}
                          {item.platform_oauth_available && (
                            <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded font-medium">
                              Platform OAuth
                            </span>
                          )}
                        </div>
                      </div>

                      {item.updated_at && (
                        <div className="flex items-center justify-between pt-1 border-t border-[#E2E8E7]/60 text-[10px] text-[#64748B]">
                          <span className="flex items-center gap-1">
                            <Clock className="h-2.5 w-2.5 text-slate-400" /> Last updated:
                          </span>
                          <span className="font-medium text-slate-600">
                            {formatLastUpdated(item.updated_at)}
                          </span>
                        </div>
                      )}
                    </div>
                  </CardContent>

                  <CardFooter className="pt-2 border-t border-[#E2E8E7] flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {/* Primary Action Button */}
                      {item.status === "authorization_required" ? (
                        <Button
                          size="sm"
                          data-testid={`btn-connect-${item.id}`}
                          onClick={() => handleInitiateOAuth(item)}
                          className="bg-[#087F72] hover:bg-[#06655B] text-white text-xs font-semibold shadow-2xs"
                        >
                          <KeyRound className="h-3.5 w-3.5 mr-1.5" />
                          Connect with OAuth
                        </Button>
                      ) : null}

                      <Button
                        size="sm"
                        data-testid={`btn-configure-${item.id}`}
                        onClick={() => {
                          setSelectedProvider(item);
                          setActiveTab("credentials");
                        }}
                        className={`text-xs font-semibold ${
                          item.status === "authorization_required"
                            ? "bg-slate-100 hover:bg-slate-200 text-[#202B33] border border-[#E2E8E7]"
                            : item.status === "connected" || item.has_credentials
                            ? "bg-[#24433F] hover:bg-[#1B3330] text-white"
                            : "bg-[#24433F] hover:bg-[#1B3330] text-white"
                        }`}
                      >
                        <Plug className="h-3.5 w-3.5 mr-1.5" />
                        {item.status === "connected" || item.has_credentials ? "Manage Configuration" : "Configure"}
                      </Button>

                      {/* Setup Guide Button */}
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`btn-setup-guide-${item.id}`}
                        onClick={() => {
                          setSelectedProvider(item);
                          setActiveTab("guide");
                        }}
                        className="border-[#E2E8E7] text-[#202B33] hover:bg-slate-50 text-xs"
                      >
                        <BookOpen className="h-3.5 w-3.5 mr-1.5 text-[#087F72]" />
                        Setup Guide
                      </Button>
                    </div>

                    <div className="flex items-center gap-1.5">
                      {/* Test Connection Button */}
                      {item.connection_id && (
                        <Button
                          size="sm"
                          variant="ghost"
                          data-testid={`btn-test-${item.id}`}
                          onClick={() => testMutation.mutate(item.connection_id!)}
                          disabled={testMutation.isPending}
                          className="text-xs text-[#087F72] hover:bg-[#087F72]/10 h-8 px-2.5"
                          title="Run API diagnostic test"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 mr-1 ${testMutation.isPending ? "animate-spin" : ""}`} />
                          Test
                        </Button>
                      )}

                      {/* Disconnect Button */}
                      {item.connection_id && (
                        <Button
                          size="sm"
                          variant="ghost"
                          data-testid={`btn-disconnect-${item.id}`}
                          onClick={() => setDisconnectTarget(item)}
                          className="text-xs text-rose-600 hover:bg-rose-50 hover:text-rose-700 h-8 px-2"
                          title="Disconnect application"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </CardFooter>
                </Card>
              );
            })}
      </div>

      {/* Guided Configuration & Setup Modal */}
      {selectedProvider && (
        <Dialog open={!!selectedProvider} onOpenChange={(open) => !open && setSelectedProvider(null)}>
          <DialogContent className="max-w-2xl max-h-[88vh] overflow-y-auto bg-[#FFFFFF] border-[#E2E8E7]">
            <DialogHeader className="border-b border-[#E2E8E7] pb-3.5">
              <div className="flex items-center justify-between pr-6">
                <div className="flex items-center gap-2.5">
                  <div className="h-8 w-8 rounded-lg bg-[#087F72]/10 border border-[#087F72]/20 flex items-center justify-center text-[#087F72]">
                    <Plug className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <DialogTitle className="text-base font-bold text-[#202B33]">
                        Configure {selectedProvider.name}
                      </DialogTitle>
                      {isDirty && (
                        <Badge
                          variant="outline"
                          data-testid="badge-unsaved-changes"
                          className="text-[10px] bg-amber-50 text-amber-700 border-amber-300 animate-pulse font-semibold"
                        >
                          Unsaved Changes
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <DialogDescription className="text-xs text-[#64748B]">
                        {selectedProvider.category}
                      </DialogDescription>
                      {selectedProvider.updated_at && (
                        <>
                          <span className="text-slate-300">•</span>
                          <span className="text-[11px] text-[#64748B] flex items-center gap-1">
                            <Clock className="h-3 w-3" /> Last updated: {formatLastUpdated(selectedProvider.updated_at)}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Modal Navigation Tabs */}
              <div className="flex gap-2 pt-3">
                <button
                  type="button"
                  data-testid="tab-guide"
                  onClick={() => setActiveTab("guide")}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
                    activeTab === "guide"
                      ? "bg-[#24433F] text-white"
                      : "bg-slate-100 text-[#64748B] hover:text-[#202B33]"
                  }`}
                >
                  Interactive Setup Guide
                </button>
                <button
                  type="button"
                  data-testid="tab-credentials"
                  onClick={() => setActiveTab("credentials")}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 ${
                    activeTab === "credentials"
                      ? "bg-[#24433F] text-white"
                      : "bg-slate-100 text-[#64748B] hover:text-[#202B33]"
                  }`}
                >
                  <span>App Credentials Form</span>
                  {isDirty ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                  ) : isConfigured ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  ) : null}
                </button>
              </div>
            </DialogHeader>

            {/* TAB 1: INTERACTIVE SETUP GUIDE */}
            {activeTab === "guide" && (
              <div className="py-2 space-y-4">
                {isGuideLoading ? (
                  <div className="space-y-3">
                    <Skeleton className="h-20 w-full" />
                    <Skeleton className="h-20 w-full" />
                  </div>
                ) : setupGuide ? (
                  <>
                    {/* Setup Guide Header & Portal Link */}
                    <div className="bg-[#F7F8F6] border border-[#E2E8E7] rounded-lg p-3.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold text-[#202B33]">
                          Official Developer Portal: {setupGuide.portal_name}
                        </div>
                        <p className="text-[11px] text-[#64748B] mt-0.5">
                          Create your developer application and register FlowPilot&apos;s callback URL.
                        </p>
                      </div>
                      <a
                        href={setupGuide.portal_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-[#087F72] hover:bg-[#06655B] px-3 py-1.5 rounded-md shrink-0 shadow-2xs"
                      >
                        Open {setupGuide.portal_name}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    </div>

                    {/* Environment-Specific Callback URL */}
                    {setupGuide.callback_url && (
                      <div className="border border-[#E2E8E7] bg-slate-50/70 rounded-lg p-3 space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-[#202B33]">
                            Authorized Redirect Callback URL
                          </span>
                          <span className="text-[10px] text-[#64748B]">
                            Register this exact URL in your provider console
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <code className="text-[11px] font-mono bg-white px-2.5 py-1.5 rounded border border-[#E2E8E7] text-[#202B33] flex-1 truncate">
                            {setupGuide.callback_url}
                          </code>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            data-testid="btn-copy-callback"
                            onClick={() => handleCopy(setupGuide.callback_url!, "callback")}
                            className="shrink-0 h-8 text-xs border-[#E2E8E7]"
                          >
                            <Copy className="h-3 w-3 mr-1" />
                            {copiedUrl === "callback" ? "Copied!" : "Copy"}
                          </Button>
                        </div>
                      </div>
                    )}

                    {/* WhatsApp Webhook Callback URL */}
                    {setupGuide.webhook_url && (
                      <div className="border border-[#E2E8E7] bg-slate-50/70 rounded-lg p-3 space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-[#202B33]">
                            WhatsApp Webhook Callback URL
                          </span>
                          <span className="text-[10px] text-[#64748B]">
                            Subscribe to messages in WhatsApp &gt; Configuration
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <code className="text-[11px] font-mono bg-white px-2.5 py-1.5 rounded border border-[#E2E8E7] text-[#202B33] flex-1 truncate">
                            {setupGuide.webhook_url}
                          </code>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => handleCopy(setupGuide.webhook_url!, "webhook")}
                            className="shrink-0 h-8 text-xs border-[#E2E8E7]"
                          >
                            <Copy className="h-3 w-3 mr-1" />
                            {copiedUrl === "webhook" ? "Copied!" : "Copy"}
                          </Button>
                        </div>
                      </div>
                    )}

                    {/* Step by step interactive instructions */}
                    <div className="space-y-3">
                      <div className="text-xs font-bold text-[#202B33] tracking-wide uppercase">
                        Step-by-Step Instructions
                      </div>
                      {setupGuide.steps.map((step) => (
                        <div
                          key={step.step_number}
                          className="bg-white border border-[#E2E8E7] rounded-lg p-3.5 shadow-2xs space-y-2"
                        >
                          <div className="flex items-start gap-2.5">
                            <span className="h-5 w-5 rounded-full bg-[#087F72] text-white flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">
                              {step.step_number}
                            </span>
                            <div className="flex-1">
                              <h5 className="text-xs font-bold text-[#202B33]">
                                {step.title}
                              </h5>
                              <p className="text-xs text-[#64748B] mt-1 leading-relaxed">
                                {step.instructions}
                              </p>
                              {step.tip && (
                                <div className="mt-2 text-[11px] bg-amber-500/10 border border-amber-500/20 text-amber-800 dark:text-amber-300 p-2 rounded flex items-center gap-1.5">
                                  <Info className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                                  <span>{step.tip}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="pt-2 flex justify-end">
                      <Button
                        size="sm"
                        onClick={() => setActiveTab("credentials")}
                        className="bg-[#24433F] hover:bg-[#1B3330] text-white text-xs font-semibold"
                      >
                        Proceed to Enter Credentials
                        <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
                      </Button>
                    </div>
                  </>
                ) : null}
              </div>
            )}

            {/* TAB 2: CREDENTIALS FORM */}
            {activeTab === "credentials" && (
              <form onSubmit={handleSaveCredentials} className="py-2 space-y-4">
                {/* Reauthorization Notice on Connected Provider credential edit */}
                {selectedProvider.status === "connected" &&
                  ((isReplacingSecret && clientSecret.length > 0) ||
                    (isReplacingToken && accessToken.length > 0) ||
                    clientId !== initialValues.clientId) && (
                    <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-xs text-amber-800 dark:text-amber-300 flex items-start gap-2">
                      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-600" />
                      <div>
                        <span className="font-semibold">Reauthorization Notice:</span>
                        <span className="block mt-0.5">
                          Replacing credentials for an active connection will clear current access tokens. You will need to complete authorization again with the new credentials.
                        </span>
                      </div>
                    </div>
                  )}

                {selectedProvider.id === "whatsapp" ? (
                  // WHATSAPP BUSINESS CREDENTIALS
                  <div className="space-y-3.5">
                    {/* Meta Access Token with Masked Configured State & Replace Toggle */}
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-semibold text-[#202B33] flex items-center gap-1.5">
                          Meta Access Token{" "}
                          {!selectedProvider.has_access_token && <span className="text-red-500">*</span>}
                        </label>
                        {selectedProvider.has_access_token && !isReplacingToken && (
                          <span className="text-[10px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200 font-medium flex items-center gap-1">
                            <ShieldCheck className="h-3 w-3" /> Configured &amp; Encrypted
                          </span>
                        )}
                      </div>

                      {selectedProvider.has_access_token && !isReplacingToken ? (
                        <div className="flex items-center justify-between p-2.5 bg-slate-50 border border-slate-200 rounded-md">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs tracking-widest text-slate-700 select-none">
                              ••••••••••••••••••••••••
                            </span>
                          </div>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            data-testid="btn-replace-token"
                            onClick={() => {
                              setIsReplacingToken(true);
                              setJustSaved(false);
                            }}
                            className="h-7 text-xs border-[#E2E8E7] hover:bg-slate-100 text-[#202B33]"
                          >
                            Replace Token
                          </Button>
                        </div>
                      ) : (
                        <div>
                          <div className="relative mt-1">
                            <Input
                              type={showSecret ? "text" : "password"}
                              data-testid="input-access-token"
                              value={accessToken}
                              onChange={(e) => {
                                setAccessToken(e.target.value);
                                setJustSaved(false);
                              }}
                              placeholder={
                                selectedProvider.has_access_token
                                  ? "Enter new replacement Meta access token..."
                                  : "EAAGxxxxxxxxxxxxxxxxxxxx"
                              }
                              required={!selectedProvider.has_access_token}
                              className="pr-10 text-xs font-mono"
                            />
                            <button
                              type="button"
                              onClick={() => setShowSecret(!showSecret)}
                              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                            >
                              {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                          </div>
                          {selectedProvider.has_access_token && isReplacingToken && (
                            <div className="flex items-center justify-between mt-1.5">
                              <span className="text-[11px] text-amber-700">
                                Leave blank or cancel to keep existing token.
                              </span>
                              <button
                                type="button"
                                onClick={() => {
                                  setIsReplacingToken(false);
                                  setAccessToken("");
                                }}
                                className="text-[11px] text-slate-600 hover:text-slate-900 underline font-medium"
                              >
                                Cancel replacement
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                      <p className="text-[11px] text-[#64748B] mt-1">
                        System user token or temporary test token with whatsapp_business_messaging permission.
                      </p>
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-[#202B33] flex items-center gap-1.5">
                        Phone Number ID <span className="text-red-500">*</span>
                      </label>
                      <Input
                        type="text"
                        data-testid="input-phone-number-id"
                        value={phoneNumberId}
                        onChange={(e) => {
                          setPhoneNumberId(e.target.value);
                          setJustSaved(false);
                        }}
                        placeholder="104829104812345"
                        required
                        className="mt-1 text-xs"
                      />
                      <p className="text-[11px] text-[#64748B] mt-1">
                        Identifies the WhatsApp Cloud API sender in your Meta app under WhatsApp &gt; API Setup.
                      </p>
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-[#202B33]">
                        WhatsApp Business Account ID (WABA) (Optional)
                      </label>
                      <Input
                        type="text"
                        data-testid="input-business-account-id"
                        value={businessAccountId}
                        onChange={(e) => {
                          setBusinessAccountId(e.target.value);
                          setJustSaved(false);
                        }}
                        placeholder="102938475612345"
                        className="mt-1 text-xs"
                      />
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-semibold text-[#202B33]">
                          Meta App Secret (Optional)
                        </label>
                        <Input
                          type="password"
                          value={appSecret}
                          onChange={(e) => {
                            setAppSecret(e.target.value);
                            setJustSaved(false);
                          }}
                          placeholder={
                            selectedProvider.has_app_secret
                              ? "•••••••• (Configured)"
                              : "HMAC webhook verification"
                          }
                          className="mt-1 text-xs"
                        />
                      </div>
                      <div>
                        <label className="text-xs font-semibold text-[#202B33]">
                          Webhook Verify Token (Optional)
                        </label>
                        <Input
                          type="text"
                          value={webhookVerifyToken}
                          onChange={(e) => {
                            setWebhookVerifyToken(e.target.value);
                            setJustSaved(false);
                          }}
                          placeholder="Custom verify challenge"
                          className="mt-1 text-xs"
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  // OAUTH PROVIDERS (GOOGLE, SLACK)
                  <div className="space-y-3.5">
                    <div>
                      <label className="text-xs font-semibold text-[#202B33] flex items-center gap-1.5">
                        {selectedProvider.id === "slack" ? "Slack Client ID" : "Google OAuth Client ID"}{" "}
                        <span className="text-red-500">*</span>
                      </label>
                      <Input
                        type="text"
                        data-testid="input-client-id"
                        value={clientId}
                        onChange={(e) => {
                          setClientId(e.target.value);
                          setJustSaved(false);
                        }}
                        placeholder={
                          selectedProvider.id === "slack"
                            ? "123456789.987654321"
                            : "123456789-abcdefg.apps.googleusercontent.com"
                        }
                        required
                        className="mt-1 text-xs font-mono"
                      />
                      <p className="text-[11px] text-[#64748B] mt-1">
                        Identifies the developer application you created with this provider.
                      </p>
                    </div>

                    {/* Sensitive Client Secret with Masked State & Replace Toggle */}
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-semibold text-[#202B33] flex items-center gap-1.5">
                          {selectedProvider.id === "slack" ? "Slack Client Secret" : "Google OAuth Client Secret"}{" "}
                          {!selectedProvider.has_client_secret && <span className="text-red-500">*</span>}
                        </label>
                        {selectedProvider.has_client_secret && !isReplacingSecret && (
                          <span className="text-[10px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200 font-medium flex items-center gap-1">
                            <ShieldCheck className="h-3 w-3" /> Configured &amp; Encrypted
                          </span>
                        )}
                      </div>

                      {selectedProvider.has_client_secret && !isReplacingSecret ? (
                        <div className="flex items-center justify-between p-2.5 bg-slate-50 border border-slate-200 rounded-md">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs tracking-widest text-slate-700 select-none">
                              ••••••••••••••••••••••••
                            </span>
                          </div>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            data-testid="btn-replace-secret"
                            onClick={() => {
                              setIsReplacingSecret(true);
                              setJustSaved(false);
                            }}
                            className="h-7 text-xs border-[#E2E8E7] hover:bg-slate-100 text-[#202B33]"
                          >
                            Replace Secret
                          </Button>
                        </div>
                      ) : (
                        <div>
                          <div className="relative mt-1">
                            <Input
                              type={showSecret ? "text" : "password"}
                              data-testid="input-client-secret"
                              value={clientSecret}
                              onChange={(e) => {
                                setClientSecret(e.target.value);
                                setJustSaved(false);
                              }}
                              placeholder={
                                selectedProvider.has_client_secret
                                  ? "Enter new replacement secret..."
                                  : "Enter secret key"
                              }
                              required={!selectedProvider.has_client_secret}
                              className="pr-10 text-xs font-mono"
                            />
                            <button
                              type="button"
                              data-testid="btn-toggle-secret-visibility"
                              onClick={() => setShowSecret(!showSecret)}
                              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                            >
                              {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                          </div>
                          {selectedProvider.has_client_secret && isReplacingSecret && (
                            <div className="flex items-center justify-between mt-1.5">
                              <span className="text-[11px] text-amber-700">
                                Leave blank or cancel to keep your existing encrypted secret.
                              </span>
                              <button
                                type="button"
                                onClick={() => {
                                  setIsReplacingSecret(false);
                                  setClientSecret("");
                                }}
                                className="text-[11px] text-slate-600 hover:text-slate-900 underline font-medium"
                              >
                                Cancel replacement
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                      <p className="text-[11px] text-[#64748B] mt-1">
                        A confidential value used by FlowPilot&apos;s backend during authorization code exchange.
                      </p>
                    </div>

                    {/* Google Gmail & Sheets Reuse Context Note */}
                    {(selectedProvider.id === "gmail" || selectedProvider.id === "sheets") && (
                      <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-xs text-emerald-800 dark:text-emerald-300 flex items-start gap-2">
                        <Info className="h-4 w-4 shrink-0 mt-0.5 text-emerald-600" />
                        <div>
                          <span className="font-semibold">Shared Google App Credentials:</span>
                          <span className="block mt-0.5">
                            Gmail and Google Sheets securely share your Google OAuth project credentials. Saving here updates your application client for both services.
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <DialogFooter className="border-t border-[#E2E8E7] pt-3.5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {selectedProvider.status === "authorization_required" && (
                      <Button
                        type="button"
                        size="sm"
                        data-testid="btn-authorize-modal"
                        onClick={() => handleInitiateOAuth(selectedProvider)}
                        className="bg-[#087F72] hover:bg-[#06655B] text-white text-xs font-semibold"
                      >
                        <KeyRound className="h-3.5 w-3.5 mr-1.5" />
                        Authorize with OAuth Now
                      </Button>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedProvider(null)}
                      className="border-[#E2E8E7] text-xs text-[#202B33]"
                    >
                      Close
                    </Button>
                    <Button
                      type="submit"
                      size="sm"
                      data-testid="btn-save-credentials"
                      disabled={saveBtn.disabled}
                      className={`text-xs font-semibold ${saveBtn.className}`}
                    >
                      {saveBtn.icon}
                      {saveBtn.label}
                    </Button>
                  </div>
                </DialogFooter>
              </form>
            )}
          </DialogContent>
        </Dialog>
      )}

      {/* Disconnect Confirmation Dialog */}
      {disconnectTarget && (
        <Dialog open={!!disconnectTarget} onOpenChange={(open) => !open && setDisconnectTarget(null)}>
          <DialogContent className="max-w-md bg-white border-[#E2E8E7]">
            <DialogHeader>
              <div className="flex items-center gap-2 text-rose-600 mb-1">
                <AlertTriangle className="h-5 w-5" />
                <DialogTitle className="text-base font-bold text-[#202B33]">
                  Disconnect {disconnectTarget.name}?
                </DialogTitle>
              </div>
              <DialogDescription className="text-xs text-[#64748B] leading-relaxed">
                Disconnecting will remove your encrypted stored credentials and revoke active authorization tokens for this service.
                Existing workflow history and past audit records will be securely preserved.
              </DialogDescription>
            </DialogHeader>

            <DialogFooter className="pt-3 border-t border-[#E2E8E7] flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDisconnectTarget(null)}
                className="text-xs border-[#E2E8E7]"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="destructive"
                data-testid="btn-confirm-disconnect"
                disabled={disconnectMutation.isPending}
                onClick={() => disconnectMutation.mutate(disconnectTarget.connection_id!)}
                className="text-xs bg-rose-600 hover:bg-rose-700 text-white"
              >
                {disconnectMutation.isPending ? "Disconnecting..." : "Disconnect Service"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
