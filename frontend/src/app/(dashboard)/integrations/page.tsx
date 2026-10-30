"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Mail,
  MessageSquare,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  Plug,
  Unplug,
  FileSpreadsheet,
  Activity,
  Fingerprint,
  HelpCircle,
  CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { IntegrationConnection } from "@/types";
import { getDeliveryStatusMeta } from "@/lib/delivery-status";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { formatDate } from "@/lib/utils";

function IntegrationsPageContent() {
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [disconnectTarget, setDisconnectTarget] = React.useState<IntegrationConnection | null>(null);
  const [showWhatsAppSetup, setShowWhatsAppSetup] = React.useState(false);

  // Check callback success
  React.useEffect(() => {
    const status = searchParams.get("status");
    const provider = searchParams.get("provider");
    if (status === "success" && provider) {
      toast.success(`Successfully connected ${provider.toUpperCase()}`, {
        description: "Your credentials have been securely stored with AES-256-GCM encryption.",
      });
      // Invalidate queries to pick up the new connection
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
    }
  }, [searchParams, queryClient]);

  // Query providers
  const { data: providers = [], isLoading: isProvidersLoading } = useQuery({
    queryKey: ["integrations", "providers"],
    queryFn: () => api.integrations.listProviders(),
  });

  // Query connections
  const {
    data: connections = [],
    isLoading: isConnectionsLoading,
    isRefetching,
    refetch,
  } = useQuery({
    queryKey: ["integrations", "connections"],
    queryFn: () => api.integrations.listConnections(),
  });

  // Query WhatsApp status (Admin / Deployment configured)
  const {
    data: whatsappStatus,
    isLoading: isWhatsAppLoading,
  } = useQuery({
    queryKey: ["integrations", "whatsapp-status"],
    queryFn: () => api.integrations.getWhatsAppStatus(),
  });

  // Query recent external actions
  const { data: actions = [], isLoading: isActionsLoading } = useQuery({
    queryKey: ["integrations", "actions"],
    queryFn: () => api.integrations.listActions(25),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => api.integrations.testConnection(id),
    onSuccess: (data) => {
      toast.success("Connection test passed", {
        description: data.message || `Provider ${data.provider} verified successfully.`,
      });
      queryClient.invalidateQueries({ queryKey: ["integrations", "connections"] });
    },
    onError: (err: any) => {
      toast.error("Connection test failed", {
        description: err.message || "Failed to reach external API.",
      });
    },
  });

  const testWhatsAppMutation = useMutation({
    mutationFn: () => api.integrations.testWhatsApp(),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success("WhatsApp Connection Verified", {
          description: data.message || "Meta Cloud API credentials and Phone Number ID confirmed active.",
        });
      } else {
        toast.error("WhatsApp Verification Failed", {
          description: data.message || "Unable to reach Meta Cloud API with configured credentials.",
        });
      }
      queryClient.invalidateQueries({ queryKey: ["integrations", "whatsapp-status"] });
    },
    onError: (err: any) => {
      toast.error("WhatsApp connection test failed", {
        description: err.message || "Failed to reach Meta Cloud API.",
      });
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: (id: string) => api.integrations.disconnectConnection(id),
    onSuccess: () => {
      toast.info("Integration disconnected", {
        description: "Access tokens and refresh tokens have been removed.",
      });
      setDisconnectTarget(null);
      queryClient.invalidateQueries({ queryKey: ["integrations", "connections"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring", "health"] });
    },
    onError: (err: any) => {
      toast.error("Failed to disconnect", {
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  const handleConnect = async (providerId: string, service?: string) => {
    try {
      toast.loading("Generating secure authorization URL...", { id: "oauth-init" });
      const res = await api.integrations.getAuthorizeUrl(providerId, service);
      toast.dismiss("oauth-init");
      if (res.authorization_url) {
        window.location.href = res.authorization_url;
      }
    } catch (err: any) {
      toast.dismiss("oauth-init");
      toast.error("Could not initiate authorization", {
        description: err.message || "Check whether provider is configured on the backend.",
      });
    }
  };

  // Find connection for a given provider
  const findConnection = (providerId: string, service?: string) => {
    return connections.find(
      (c) => c.provider.toLowerCase() === providerId.toLowerCase() && (!service || c.service === service)
    );
  };


  return (
    <div className="space-y-8">
      <PageHeader
        title="External Integrations & Business Channels"
        description="Connect and manage authorized business services (Gmail, Google Sheets, Slack, WhatsApp Business) for real-world agent actions with granular scopes and replay-resistant OAuth."
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            refetch();
            queryClient.invalidateQueries({ queryKey: ["integrations", "whatsapp-status"] });
          }}
          disabled={isRefetching}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isRefetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </PageHeader>

      {/* App Connections Contextual Banner */}
      <div className="bg-[#FFFFFF] border border-[#E2E8E7] rounded-xl p-4 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="p-2.5 rounded-lg bg-[#087F72]/10 border border-[#087F72]/20 text-[#087F72] shrink-0 mt-0.5 sm:mt-0">
            <Plug className="h-5 w-5" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-[#202B33]">Looking to configure custom external credentials?</h4>
            <p className="text-xs text-[#64748B] mt-0.5 leading-relaxed">
              Use <strong>App Connections</strong> to configure your own Google OAuth client, Slack app tokens, or Meta WhatsApp Cloud API credentials with interactive setup guides.
            </p>
          </div>
        </div>
        <Link href="/settings/connections" className="shrink-0">
          <Button size="sm" className="bg-[#24433F] hover:bg-[#1B3330] text-white text-xs font-semibold">
            Open App Connections
            <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
          </Button>
        </Link>
      </div>

      {/* Service Cards */}
      <div className="space-y-4">
        <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-primary" />
          Supported Automation Channels
        </h2>

        {isProvidersLoading || isConnectionsLoading || isWhatsAppLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-64 w-full rounded-xl" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* Google / Gmail */}
            {(() => {
              const googleProv = providers.find((p) => p.id === "google");
              const gmailConn = findConnection("google", "gmail") || findConnection("google");
              const isConfigured = googleProv ? googleProv.is_configured : true;

              return (
                <Card className="flex flex-col justify-between transition hover:shadow-md border-border">
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div className="p-2.5 rounded-xl bg-red-500/10 border border-red-500/20">
                        <Mail className="h-6 w-6 text-red-500" />
                      </div>
                      <Badge
                        variant={gmailConn ? "success" : "secondary"}
                        className="text-xs"
                      >
                        {gmailConn ? "Connected" : "Not Connected"}
                      </Badge>
                    </div>
                    <CardTitle className="text-base font-semibold mt-3">Google (Gmail)</CardTitle>
                    <CardDescription className="text-xs">
                      Send operational emails, trigger notifications, and dispatch workflow reports.
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="space-y-3 pb-3 text-xs flex-1">
                    {!isConfigured && (
                      <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400">
                        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                        <span>OAuth Client ID not set in backend .env (GOOGLE_CLIENT_ID).</span>
                      </div>
                    )}

                    {gmailConn ? (
                      <div className="space-y-2 bg-muted/40 p-3 rounded-lg border border-border">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Account:</span>
                          <span className="font-medium text-foreground">
                            {gmailConn.external_account_name || gmailConn.external_account_id || "Google Account"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Status:</span>
                          <span className="capitalize text-emerald-600 font-medium">
                            {gmailConn.status}
                          </span>
                        </div>
                        {gmailConn.last_verified_at && (
                          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                            <span>Last verified:</span>
                            <span>{formatDate(gmailConn.last_verified_at)}</span>
                          </div>
                        )}
                        <div className="pt-1">
                          <span className="text-[11px] text-muted-foreground block mb-1">
                            Granted Scopes:
                          </span>
                          <div className="flex flex-wrap gap-1">
                            {gmailConn.granted_scopes.map((s) => (
                              <Badge key={s} variant="outline" className="text-[10px] font-mono">
                                {s.split("/").pop()}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-muted-foreground space-y-1">
                        <span className="font-medium text-foreground block">Capabilities:</span>
                        <ul className="list-disc list-inside text-[11px] space-y-0.5">
                          <li>Dispatch customer notifications</li>
                          <li>Human-in-the-loop email confirmations</li>
                          <li>Digest verified payloads</li>
                        </ul>
                      </div>
                    )}
                  </CardContent>

                  <CardFooter className="pt-3 border-t border-border bg-muted/20 flex items-center justify-between">
                    {gmailConn ? (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs h-8"
                          onClick={() => testMutation.mutate(gmailConn.id)}
                          disabled={testMutation.isPending}
                        >
                          <RefreshCw className="h-3.5 w-3.5 mr-1" />
                          Test
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs h-8 text-rose-600 hover:text-rose-700 hover:bg-rose-500/10"
                          onClick={() => setDisconnectTarget(gmailConn)}
                        >
                          <Unplug className="h-3.5 w-3.5 mr-1" />
                          Disconnect
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        className="w-full text-xs"
                        onClick={() => handleConnect("google", "gmail")}
                        disabled={!isConfigured}
                      >
                        Connect Google Account
                      </Button>
                    )}
                  </CardFooter>
                </Card>
              );
            })()}

            {/* Google / Google Sheets */}
            {(() => {
              const googleProv = providers.find((p) => p.id === "google");
              const sheetsConn = findConnection("google", "sheets");
              const isConfigured = googleProv ? googleProv.is_configured : true;

              return (
                <Card className="flex flex-col justify-between transition hover:shadow-md border-border">
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                        <FileSpreadsheet className="h-6 w-6 text-emerald-500" />
                      </div>
                      <Badge
                        variant={sheetsConn ? "success" : "secondary"}
                        className="text-xs"
                      >
                        {sheetsConn ? "Connected" : "Not Connected"}
                      </Badge>
                    </div>
                    <CardTitle className="text-base font-semibold mt-3">Google Sheets</CardTitle>
                    <CardDescription className="text-xs">
                      Read lead lists, append pipeline metrics, and update spreadsheets automatically.
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="space-y-3 pb-3 text-xs flex-1">
                    {!isConfigured && (
                      <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400">
                        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                        <span>OAuth Client ID not set in backend .env (GOOGLE_CLIENT_ID).</span>
                      </div>
                    )}

                    {sheetsConn ? (
                      <div className="space-y-2 bg-muted/40 p-3 rounded-lg border border-border">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Account:</span>
                          <span className="font-medium text-foreground">
                            {sheetsConn.external_account_name || sheetsConn.external_account_id || "Google Account"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Status:</span>
                          <span className="capitalize text-emerald-600 font-medium">
                            {sheetsConn.status}
                          </span>
                        </div>
                        {sheetsConn.last_verified_at && (
                          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                            <span>Last verified:</span>
                            <span>{formatDate(sheetsConn.last_verified_at)}</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-muted-foreground space-y-1">
                        <span className="font-medium text-foreground block">Capabilities:</span>
                        <ul className="list-disc list-inside text-[11px] space-y-0.5">
                          <li>Append structured rows & summaries</li>
                          <li>Fetch input records for multi-agent workflows</li>
                          <li>Bi-directional spreadsheet sync</li>
                        </ul>
                      </div>
                    )}
                  </CardContent>

                  <CardFooter className="pt-3 border-t border-border bg-muted/20 flex items-center justify-between">
                    {sheetsConn ? (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs h-8"
                          onClick={() => testMutation.mutate(sheetsConn.id)}
                          disabled={testMutation.isPending}
                        >
                          <RefreshCw className="h-3.5 w-3.5 mr-1" />
                          Test
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs h-8 text-rose-600 hover:text-rose-700 hover:bg-rose-500/10"
                          onClick={() => setDisconnectTarget(sheetsConn)}
                        >
                          <Unplug className="h-3.5 w-3.5 mr-1" />
                          Disconnect
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        className="w-full text-xs"
                        onClick={() => handleConnect("google", "sheets")}
                        disabled={!isConfigured}
                      >
                        Connect Google Sheets
                      </Button>
                    )}
                  </CardFooter>
                </Card>
              );
            })()}

            {/* Slack */}
            {(() => {
              const slackProv = providers.find((p) => p.id === "slack");
              const slackConn = findConnection("slack");
              const isConfigured = slackProv ? slackProv.is_configured : true;

              return (
                <Card className="flex flex-col justify-between transition hover:shadow-md border-border">
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20">
                        <MessageSquare className="h-6 w-6 text-amber-500" />
                      </div>
                      <Badge
                        variant={slackConn ? "success" : "secondary"}
                        className="text-xs"
                      >
                        {slackConn ? "Connected" : "Not Connected"}
                      </Badge>
                    </div>
                    <CardTitle className="text-base font-semibold mt-3">Slack</CardTitle>
                    <CardDescription className="text-xs">
                      Publish operational alerts, post execution briefs, and notify team channels.
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="space-y-3 pb-3 text-xs flex-1">
                    {!isConfigured && (
                      <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400">
                        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                        <span>OAuth Client ID not set in backend .env (SLACK_CLIENT_ID).</span>
                      </div>
                    )}

                    {slackConn ? (
                      <div className="space-y-2 bg-muted/40 p-3 rounded-lg border border-border">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Workspace:</span>
                          <span className="font-medium text-foreground">
                            {slackConn.external_account_name || slackConn.external_account_id || "Slack Workspace"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Status:</span>
                          <span className="capitalize text-emerald-600 font-medium">
                            {slackConn.status}
                          </span>
                        </div>
                        {slackConn.last_verified_at && (
                          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                            <span>Last verified:</span>
                            <span>{formatDate(slackConn.last_verified_at)}</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-muted-foreground space-y-1">
                        <span className="font-medium text-foreground block">Capabilities:</span>
                        <ul className="list-disc list-inside text-[11px] space-y-0.5">
                          <li>Post incident notices to #incidents</li>
                          <li>Send executive summary messages</li>
                          <li>Human authorization interactive alerts</li>
                        </ul>
                      </div>
                    )}
                  </CardContent>

                  <CardFooter className="pt-3 border-t border-border bg-muted/20 flex items-center justify-between">
                    {slackConn ? (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs h-8"
                          onClick={() => testMutation.mutate(slackConn.id)}
                          disabled={testMutation.isPending}
                        >
                          <RefreshCw className="h-3.5 w-3.5 mr-1" />
                          Test
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs h-8 text-rose-600 hover:text-rose-700 hover:bg-rose-500/10"
                          onClick={() => setDisconnectTarget(slackConn)}
                        >
                          <Unplug className="h-3.5 w-3.5 mr-1" />
                          Disconnect
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        className="w-full text-xs"
                        onClick={() => handleConnect("slack")}
                        disabled={!isConfigured}
                      >
                        Connect Slack Workspace
                      </Button>
                    )}
                  </CardFooter>
                </Card>
              );
            })()}

            {/* WhatsApp Business (Cloud API) */}
            {(() => {
              const isConfigured = whatsappStatus?.is_configured || false;

              return (
                <Card className="flex flex-col justify-between transition hover:shadow-md border-border">
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-[#25D366]">
                        <svg
                          className="h-6 w-6 fill-current"
                          viewBox="0 0 24 24"
                          aria-label="WhatsApp"
                        >
                          <path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-6.305 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981zm11.387-5.464c-.074-.124-.272-.198-.57-.347-.297-.149-1.758-.868-2.031-.967-.272-.099-.47-.149-.669.149-.198.297-.768.967-.941 1.165-.173.198-.347.223-.644.074-.297-.149-1.255-.462-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.297-.347.446-.521.151-.172.2-.296.3-.495.099-.198.05-.372-.025-.521-.075-.148-.669-1.611-.916-2.206-.242-.579-.487-.501-.669-.51l-.57-.01c-.198 0-.52.074-.792.372s-1.04 1.016-1.04 2.479 1.065 2.876 1.213 3.074c.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.626.712.226 1.36.194 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.695.248-1.29.173-1.414z" />
                        </svg>
                      </div>
                      <Badge
                        variant={isConfigured ? "success" : "secondary"}
                        className="text-xs"
                      >
                        {isConfigured ? "Configured" : "Not Configured"}
                      </Badge>
                    </div>
                    <CardTitle className="text-base font-semibold mt-3">
                      WhatsApp Business
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Official Meta Cloud API for automated notifications and pre-approved template dispatches.
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="space-y-3 pb-3 text-xs flex-1">
                    {!isConfigured && (
                      <div className="flex flex-col gap-1.5 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400">
                        <div className="flex items-center gap-1.5 font-semibold text-[11px]">
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                          <span>Missing Backend Credentials</span>
                        </div>
                        <p className="text-[11px] text-muted-foreground">
                          Set the required environment variables in backend .env:
                        </p>
                        <div className="flex flex-wrap gap-1 mt-0.5">
                          {(whatsappStatus?.missing_fields && whatsappStatus.missing_fields.length > 0
                            ? whatsappStatus.missing_fields
                            : ["WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_APP_SECRET"]
                          ).map((field) => (
                            <Badge
                              key={field}
                              variant="outline"
                              className="text-[10px] font-mono text-amber-700 dark:text-amber-400 border-amber-500/30"
                            >
                              {field}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {isConfigured ? (
                      <div className="space-y-2 bg-muted/40 p-3 rounded-lg border border-border">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Phone Number ID:</span>
                          <span className="font-mono font-medium text-foreground">
                            {whatsappStatus?.masked_phone_number_id || "Configured"}
                          </span>
                        </div>
                        {whatsappStatus?.masked_business_account_id && (
                          <div className="flex items-center justify-between">
                            <span className="text-muted-foreground">Business Account ID:</span>
                            <span className="font-mono font-medium text-foreground">
                              {whatsappStatus.masked_business_account_id}
                            </span>
                          </div>
                        )}
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Graph API:</span>
                          <span className="font-mono text-foreground font-medium">
                            {whatsappStatus?.graph_api_version || "v21.0"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-muted-foreground">Connection Model:</span>
                          <span className="text-emerald-600 dark:text-emerald-400 font-medium">
                            Admin / Deployment
                          </span>
                        </div>
                      </div>
                    ) : (
                      <div className="text-muted-foreground space-y-1">
                        <span className="font-medium text-foreground block">Capabilities:</span>
                        <ul className="list-disc list-inside text-[11px] space-y-0.5">
                          <li>24-hour customer service direct messages</li>
                          <li>Meta-approved business template dispatches</li>
                          <li>Delivery receipt tracking (sent/delivered/read)</li>
                          <li>Mandatory human approval gate</li>
                        </ul>
                      </div>
                    )}
                  </CardContent>

                  <CardFooter className="pt-3 border-t border-border bg-muted/20 flex items-center justify-between gap-2">
                    {isConfigured ? (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs h-8 flex-1"
                          onClick={() => testWhatsAppMutation.mutate()}
                          disabled={testWhatsAppMutation.isPending}
                        >
                          <RefreshCw
                            className={`h-3.5 w-3.5 mr-1 ${
                              testWhatsAppMutation.isPending ? "animate-spin" : ""
                            }`}
                          />
                          Test Connection
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs h-8 text-muted-foreground hover:text-foreground"
                          onClick={() => setShowWhatsAppSetup(true)}
                        >
                          <HelpCircle className="h-3.5 w-3.5 mr-1" />
                          Guide
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        className="w-full text-xs"
                        onClick={() => setShowWhatsAppSetup(true)}
                      >
                        <HelpCircle className="h-3.5 w-3.5 mr-1.5" />
                        Setup Instructions
                      </Button>
                    )}
                  </CardFooter>
                </Card>
              );
            })()}
          </div>
        )}
      </div>

      {/* External Action Audit Log */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            External Action Audit Log
          </h2>
          <span className="text-xs text-muted-foreground">
            Idempotency & parameter digests cryptographically logged
          </span>
        </div>

        {isActionsLoading ? (
          <Skeleton className="h-48 w-full rounded-xl" />
        ) : actions.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-xs text-muted-foreground">
              No external actions have been executed yet. Run an agent workflow that triggers Slack, Gmail, Google Sheets, or WhatsApp to see audit events.
            </CardContent>
          </Card>
        ) : (
          <div className="rounded-xl border border-border overflow-hidden bg-card">
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="bg-muted/50 text-[11px] uppercase font-medium text-muted-foreground border-b border-border">
                  <tr>
                    <th className="py-3 px-4">Operation</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Parameter Digest</th>
                    <th className="py-3 px-4">Timestamp</th>
                    <th className="py-3 px-4">Action ID</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {actions.map((act) => (
                    <tr key={act.id} className="hover:bg-muted/30 transition-colors">
                      <td className="py-3 px-4 font-mono font-medium text-foreground">
                        <span className="flex items-center gap-1.5">
                          {act.operation.startsWith("whatsapp_") ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 font-mono"
                            >
                              WhatsApp
                            </Badge>
                          ) : act.operation.startsWith("gmail_") || act.operation === "send_email" ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20 font-mono"
                            >
                              Gmail
                            </Badge>
                          ) : act.operation.startsWith("slack_") ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20 font-mono"
                            >
                              Slack
                            </Badge>
                          ) : act.operation.startsWith("sheets_") ? (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 font-mono"
                            >
                              Sheets
                            </Badge>
                          ) : null}
                          {act.operation}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {(() => {
                          const meta = getDeliveryStatusMeta(act);
                          return (
                            <Badge variant={meta.badgeVariant} className="text-[10px]">
                              {meta.badgeLabel}
                            </Badge>
                          );
                        })()}
                      </td>
                      <td className="py-3 px-4 font-mono text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Fingerprint className="h-3 w-3 text-muted-foreground" />
                          {act.parameter_digest.slice(0, 12)}...
                        </span>
                      </td>
                      <td className="py-3 px-4 text-muted-foreground">
                        {formatDate(act.created_at)}
                      </td>
                      <td className="py-3 px-4 font-mono text-[10px] text-muted-foreground">
                        {act.id.slice(0, 8)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Disconnect Confirmation Modal */}
      <Dialog open={!!disconnectTarget} onOpenChange={(open) => !open && setDisconnectTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-rose-600">
              <Unplug className="h-5 w-5" />
              Disconnect Integration
            </DialogTitle>
            <DialogDescription>
              Are you sure you want to disconnect &ldquo;{disconnectTarget?.provider}&rdquo;?
              Active agent workflows attempting to use this channel will fail until reconnected.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDisconnectTarget(null)}
              disabled={disconnectMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => disconnectTarget && disconnectMutation.mutate(disconnectTarget.id)}
              disabled={disconnectMutation.isPending}
            >
              {disconnectMutation.isPending ? "Disconnecting..." : "Confirm Disconnect"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* WhatsApp Cloud API Setup Guide Modal */}
      <Dialog open={showWhatsAppSetup} onOpenChange={setShowWhatsAppSetup}>
        <DialogContent className="max-w-xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-foreground">
              <div className="p-1.5 rounded-lg bg-emerald-500/10 text-[#25D366]">
                <svg className="h-5 w-5 fill-current" viewBox="0 0 24 24">
                  <path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-6.305 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981zm11.387-5.464c-.074-.124-.272-.198-.57-.347-.297-.149-1.758-.868-2.031-.967-.272-.099-.47-.149-.669.149-.198.297-.768.967-.941 1.165-.173.198-.347.223-.644.074-.297-.149-1.255-.462-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.297-.347.446-.521.151-.172.2-.296.3-.495.099-.198.05-.372-.025-.521-.075-.148-.669-1.611-.916-2.206-.242-.579-.487-.501-.669-.51l-.57-.01c-.198 0-.52.074-.792.372s-1.04 1.016-1.04 2.479 1.065 2.876 1.213 3.074c.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.626.712.226 1.36.194 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.695.248-1.29.173-1.414z" />
                </svg>
              </div>
              WhatsApp Business Cloud API Setup
            </DialogTitle>
            <DialogDescription className="text-xs">
              FlowPilot integrates with Meta&apos;s official WhatsApp Business Platform (Cloud API). Credentials are authenticated at the deployment level.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2 text-xs">
            <div className="space-y-2">
              <h4 className="font-semibold text-foreground flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                1. Meta Developer Portal Setup
              </h4>
              <p className="text-muted-foreground">
                Register at <a href="https://developers.facebook.com" target="_blank" rel="noreferrer" className="text-primary underline">developers.facebook.com</a> and create an App with type <strong>Business</strong>. Add the <strong>WhatsApp</strong> product to your App.
              </p>
            </div>

            <div className="space-y-2">
              <h4 className="font-semibold text-foreground flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                2. Environment Variables (.env)
              </h4>
              <p className="text-muted-foreground">
                Add these variables to your <code>backend/.env</code> file:
              </p>
              <pre className="bg-muted p-3 rounded-lg font-mono text-[11px] overflow-x-auto text-foreground/90 border border-border">
{`WHATSAPP_APP_ID=your_meta_app_id
WHATSAPP_APP_SECRET=your_meta_app_secret
WHATSAPP_BUSINESS_ACCOUNT_ID=your_waba_id
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_ACCESS_TOKEN=your_system_user_access_token
WHATSAPP_WEBHOOK_VERIFY_TOKEN=your_custom_webhook_secret
WHATSAPP_GRAPH_API_VERSION=v21.0`}
              </pre>
            </div>

            <div className="space-y-2">
              <h4 className="font-semibold text-foreground flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                3. Webhook Configuration
              </h4>
              <p className="text-muted-foreground">
                In Meta App Dashboard &gt; WhatsApp &gt; Configuration:
              </p>
              <ul className="list-disc list-inside space-y-1 text-muted-foreground pl-1">
                <li>Callback URL: <code>https://&lt;your-domain&gt;/api/v1/webhooks/whatsapp</code></li>
                <li>Verify Token: Matches your <code>WHATSAPP_WEBHOOK_VERIFY_TOKEN</code></li>
                <li>Webhook Subscriptions: Check <code>messages</code> to receive real-time delivery receipts (sent, delivered, read)</li>
              </ul>
            </div>

            <div className="space-y-2 bg-muted/40 p-3 rounded-lg border border-border text-muted-foreground">
              <span className="font-semibold text-foreground block">Compliance & Security Guarantee:</span>
              <p className="text-[11px] mt-0.5">
                FlowPilot cryptographically verifies all incoming webhooks using <code>X-Hub-Signature-256</code> (HMAC-SHA256). All outbound dispatches require explicit human approval and are idempotency protected.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button size="sm" onClick={() => setShowWhatsAppSetup(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function IntegrationsPage() {
  return (
    <React.Suspense
      fallback={
        <div className="flex items-center justify-center p-12 text-xs text-muted-foreground">
          Loading integrations...
        </div>
      }
    >
      <IntegrationsPageContent />
    </React.Suspense>
  );
}
