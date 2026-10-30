"use client";

import * as React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  KeyRound,
  Sparkles,
  Bot,
  CheckCircle2,
  Eye,
  EyeOff,
  Trash2,
  RefreshCw,
  Zap,
  BarChart3,
  Cpu,
  Layers,
  ShieldCheck,
  ChevronDown,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { LLMCredential } from "@/types";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
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
import { formatDate, formatCurrency } from "@/lib/utils";

export default function LLMSettingsPage() {
  const queryClient = useQueryClient();
  const [selectedProvider, setSelectedProvider] = React.useState<"gemini" | "openai" | "groq">("gemini");
  const [apiKeyInput, setApiKeyInput] = React.useState("");
  const [showApiKey, setShowApiKey] = React.useState(false);
  const [deleteTarget, setDeleteTarget] = React.useState<LLMCredential | null>(null);
  const [isModelsExpanded, setIsModelsExpanded] = React.useState(false);
  const [isAuditExpanded, setIsAuditExpanded] = React.useState(false);

  // Queries
  const { data: credentials = [] } = useQuery({
    queryKey: ["llm", "credentials"],
    queryFn: () => api.llm.listCredentials(),
  });

  const { data: preference } = useQuery({
    queryKey: ["llm", "preference"],
    queryFn: () => api.llm.getPreference(),
  });

  const {
    data: models = [],
    isLoading: isModelsLoading,
    refetch: refetchModels,
  } = useQuery({
    queryKey: ["llm", "models", selectedProvider],
    queryFn: () => api.llm.discoverModels(selectedProvider),
    retry: false,
  });

  const {
    data: usageRecords = [],
    isLoading: isUsageLoading,
    refetch: refetchUsage,
    isRefetching: isUsageRefetching,
  } = useQuery({
    queryKey: ["llm", "usage"],
    queryFn: () => api.llm.getUsageHistory(50),
  });

  // Current active credential for selected provider
  const currentCredential = credentials.find(
    (c) => c.provider.toLowerCase() === selectedProvider.toLowerCase()
  );

  // Connect credential mutation
  const connectMutation = useMutation({
    mutationFn: (body: { provider: string; api_key: string }) =>
      api.llm.connectCredential(body),
    onSuccess: (data) => {
      toast.success(`${selectedProvider.toUpperCase()} connected successfully!`, {
        description: `Key fingerprint: ${data.key_fingerprint}. Credentials encrypted via AES-256-GCM.`,
      });
      setApiKeyInput("");
      queryClient.invalidateQueries({ queryKey: ["llm"] });
    },
    onError: (err: any) => {
      toast.error("Failed to connect API key", {
        description: err.message || "Invalid API key or network connection failed.",
      });
    },
  });

  // Test credential mutation
  const testMutation = useMutation({
    mutationFn: (id: string) => api.llm.testCredential(id),
    onSuccess: (data) => {
      toast.success("LLM Connection Verified!", {
        description: data.message || `Provider ${data.provider} responded in real time.`,
      });
      queryClient.invalidateQueries({ queryKey: ["llm", "credentials"] });
    },
    onError: (err: any) => {
      toast.error("LLM Connection Test Failed", {
        description: err.message || "The provider rejected the credential.",
      });
    },
  });

  // Delete credential mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.llm.deleteCredential(id),
    onSuccess: () => {
      toast.info("Credential removed", {
        description: "Personal API key deleted and associated preferences cleared.",
      });
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["llm"] });
    },
    onError: (err: any) => {
      toast.error("Failed to delete credential", {
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  // Set default preference mutation
  const setPreferenceMutation = useMutation({
    mutationFn: ({ credentialId, modelId }: { credentialId: string; modelId: string }) =>
      api.llm.setPreference({ credential_id: credentialId, model_id: modelId }),
    onSuccess: (data) => {
      toast.success("Default Orchestrator Updated", {
        description: `${data.provider.toUpperCase()} (${data.model_id}) is now your default model.`,
      });
      queryClient.invalidateQueries({ queryKey: ["llm", "preference"] });
    },
    onError: (err: any) => {
      toast.error("Failed to update preference", {
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  // Calculate usage totals
  const totalInputTokens = usageRecords.reduce((acc, u) => acc + (u.input_tokens || 0), 0);
  const totalOutputTokens = usageRecords.reduce((acc, u) => acc + (u.output_tokens || 0), 0);
  const totalEstimatedCost = usageRecords.reduce((acc, u) => acc + (Number(u.estimated_cost) || 0), 0);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Multi-LLM BYOK & Model Orchestration"
        description="Bring Your Own Key (BYOK) for Google Gemini, OpenAI, and Groq. Keys are encrypted with AES-256-GCM, isolated per user, and used dynamically for multi-agent workflows."
      />

      {/* Provider Selector Tabs */}
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <button
          onClick={() => setSelectedProvider("gemini")}
          className={`flex items-center gap-2.5 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            selectedProvider === "gemini"
              ? "bg-primary text-primary-foreground shadow-sm"
              : "bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <Sparkles className="h-4 w-4 text-amber-300" />
          Google Gemini
          {credentials.some((c) => c.provider.toLowerCase() === "gemini") && (
            <Badge variant="success" className="text-[10px] ml-1">
              Connected
            </Badge>
          )}
        </button>

        <button
          onClick={() => setSelectedProvider("openai")}
          className={`flex items-center gap-2.5 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            selectedProvider === "openai"
              ? "bg-primary text-primary-foreground shadow-sm"
              : "bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <Bot className="h-4 w-4" />
          OpenAI
          {credentials.some((c) => c.provider.toLowerCase() === "openai") && (
            <Badge variant="success" className="text-[10px] ml-1">
              Connected
            </Badge>
          )}
        </button>

        <button
          onClick={() => setSelectedProvider("groq")}
          className={`flex items-center gap-2.5 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            selectedProvider === "groq"
              ? "bg-primary text-primary-foreground shadow-sm"
              : "bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <Zap className="h-4 w-4 text-orange-400" />
          Groq
          {credentials.some((c) => c.provider.toLowerCase() === "groq") && (
            <Badge variant="success" className="text-[10px] ml-1">
              Connected
            </Badge>
          )}
        </button>
      </div>

      {/* Credential Management Card */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base font-semibold flex items-center gap-2">
                    <KeyRound className="h-4 w-4 text-primary" />
                    {selectedProvider === "gemini"
                      ? "Google Gemini API Key"
                      : selectedProvider === "openai"
                        ? "OpenAI API Key"
                        : "Groq API Key"}
                  </CardTitle>
                  <CardDescription className="text-xs mt-1">
                    {selectedProvider === "gemini"
                      ? "Requires a Google AI Studio API key (AIza...)."
                      : selectedProvider === "openai"
                        ? "Requires an OpenAI platform API key (sk-...)."
                        : "Requires a GroqCloud API key (gsk_...)."}
                  </CardDescription>
                </div>

                {currentCredential ? (
                  <Badge variant="success" className="text-xs">
                    Connected & Active
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="text-xs">
                    Not Connected
                  </Badge>
                )}
              </div>
            </CardHeader>

            <CardContent className="space-y-4">
              {currentCredential ? (
                <div className="space-y-3 bg-muted/30 p-4 rounded-xl border border-border">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Key Fingerprint:</span>
                    <span className="font-mono font-medium text-foreground bg-background px-2 py-0.5 rounded border border-border">
                      {currentCredential.key_fingerprint}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Connected Since:</span>
                    <span className="text-foreground">{formatDate(currentCredential.created_at)}</span>
                  </div>
                  {currentCredential.last_validated_at && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">Last Validated:</span>
                      <span className="text-emerald-600 font-medium">
                        {formatDate(currentCredential.last_validated_at)}
                      </span>
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/60">
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-xs"
                      onClick={() => testMutation.mutate(currentCredential.id)}
                      disabled={testMutation.isPending}
                    >
                      <RefreshCw
                        className={`h-3.5 w-3.5 mr-1.5 ${testMutation.isPending ? "animate-spin" : ""}`}
                      />
                      Test Connection
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs text-rose-600 hover:text-rose-700 hover:bg-rose-500/10"
                      onClick={() => setDeleteTarget(currentCredential)}
                    >
                      <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                      Remove Key
                    </Button>
                  </div>
                </div>
              ) : (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (!apiKeyInput.trim()) return;
                    connectMutation.mutate({
                      provider: selectedProvider,
                      api_key: apiKeyInput.trim(),
                    });
                  }}
                  className="space-y-4"
                >
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-foreground">
                      Enter Personal API Key
                    </label>
                    <div className="relative">
                      <Input
                        type={showApiKey ? "text" : "password"}
                        placeholder={
                          selectedProvider === "gemini"
                            ? "AIzaSy..."
                            : selectedProvider === "openai"
                              ? "sk-proj-..."
                              : "gsk_..."
                        }
                        value={apiKeyInput}
                        onChange={(e) => setApiKeyInput(e.target.value)}
                        required
                        className="pr-10 text-xs font-mono"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      >
                        {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      {selectedProvider === "gemini" ? (
                        <>
                          Get an API key from{" "}
                          <a
                            href="https://aistudio.google.com/app/apikey"
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary underline hover:text-primary/80"
                          >
                            Google AI Studio
                          </a>
                          .
                        </>
                      ) : selectedProvider === "openai" ? (
                        <>
                          Get an API key from{" "}
                          <a
                            href="https://platform.openai.com/api-keys"
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary underline hover:text-primary/80"
                          >
                            OpenAI Platform
                          </a>
                          .
                        </>
                      ) : (
                        <>
                          Get an API key from{" "}
                          <a
                            href="https://console.groq.com/keys"
                            target="_blank"
                            rel="noreferrer"
                            className="text-primary underline hover:text-primary/80"
                          >
                            Groq Console
                          </a>
                          .
                        </>
                      )}
                    </p>
                  </div>

                  <Button
                    type="submit"
                    size="sm"
                    className="text-xs"
                    disabled={connectMutation.isPending || !apiKeyInput.trim()}
                  >
                    {connectMutation.isPending ? (
                      <>
                        <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                        Validating & Encrypting...
                      </>
                    ) : (
                      "Save & Connect Key"
                    )}
                  </Button>
                </form>
              )}
            </CardContent>
          </Card>

          {/* Model Discovery & Preference (Collapsible - Collapsed by Default) */}
          <Card className="overflow-hidden">
            <CardHeader
              className="pb-3 cursor-pointer select-none hover:bg-muted/30 transition-colors"
              role="button"
              tabIndex={0}
              aria-expanded={isModelsExpanded}
              aria-controls="models-inventory-section"
              onClick={() => setIsModelsExpanded(!isModelsExpanded)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setIsModelsExpanded(!isModelsExpanded);
                }
              }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="p-1 rounded bg-muted/60 text-muted-foreground shrink-0">
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 transition-transform duration-200",
                        isModelsExpanded ? "rotate-0" : "-rotate-90"
                      )}
                    />
                  </div>
                  <div>
                    <CardTitle className="text-sm font-semibold flex items-center gap-2">
                      <Cpu className="h-4 w-4 text-primary" />
                      Available Models &amp; Default Preference
                      {models.length > 0 && (
                        <Badge variant="secondary" className="text-[10px] font-normal ml-1">
                          {models.length} {models.length === 1 ? "model" : "models"}
                        </Badge>
                      )}
                    </CardTitle>
                    <CardDescription className="text-xs mt-0.5">
                      {isModelsExpanded
                        ? "Select your preferred model for multi-agent reasoning and workflow synthesis."
                        : "Click to expand model inventory and default preferences."}
                    </CardDescription>
                  </div>
                </div>

                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      refetchModels();
                    }}
                    disabled={isModelsLoading || !currentCredential}
                    className="text-xs h-7 px-2.5"
                    title="Refresh model list"
                  >
                    <RefreshCw className={cn("h-3.5 w-3.5 mr-1", isModelsLoading && "animate-spin")} />
                    Discover
                  </Button>
                </div>
              </div>
            </CardHeader>

            {isModelsExpanded && (
              <CardContent id="models-inventory-section" className="pt-2 border-t border-border/60 animate-in fade-in-50 duration-200">
                {!currentCredential ? (
                  <div className="text-xs text-muted-foreground p-6 text-center border border-dashed rounded-lg bg-muted/20">
                    Connect your {selectedProvider.toUpperCase()} API key above to discover and activate models.
                  </div>
                ) : isModelsLoading ? (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <Skeleton key={i} className="h-14 w-full rounded-lg" />
                    ))}
                  </div>
                ) : models.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-4 text-center">
                    No models discovered. Click &ldquo;Discover&rdquo; to refresh model inventory.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {models.map((m) => {
                      const isDefault =
                        preference?.provider.toLowerCase() === selectedProvider.toLowerCase() &&
                        preference?.model_id === m.id;

                      return (
                        <div
                          key={m.id}
                          className={cn(
                            "flex items-center justify-between p-3 rounded-md border transition-all",
                            isDefault
                              ? "bg-primary/5 border-primary/40 shadow-xs"
                              : "bg-muted/20 border-border hover:bg-muted/40"
                          )}
                        >
                          <div className="min-w-0 pr-3">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-xs font-semibold text-foreground">{m.name}</span>
                              <span className="font-mono text-[10px] text-muted-foreground">
                                ({m.id})
                              </span>
                              {isDefault && (
                                <Badge variant="success" className="text-[10px]">
                                  Default Orchestrator
                                </Badge>
                              )}
                            </div>
                            {m.description && (
                              <p className="text-[11px] text-muted-foreground line-clamp-1 mt-0.5">
                                {m.description}
                              </p>
                            )}
                          </div>

                          <div className="shrink-0">
                            {isDefault ? (
                              <div className="flex items-center text-xs text-[#16866B] font-medium px-2 py-1">
                                <CheckCircle2 className="h-4 w-4 mr-1 text-[#16866B]" />
                                Active
                              </div>
                            ) : (
                              <Button
                                variant="outline"
                                size="xs"
                                className="h-7 px-3 text-[11px] leading-none text-foreground font-medium flex items-center justify-center"
                                onClick={() =>
                                  setPreferenceMutation.mutate({
                                    credentialId: currentCredential.id,
                                    modelId: m.id,
                                  })
                                }
                                disabled={setPreferenceMutation.isPending}
                              >
                                Set as Default
                              </Button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            )}
          </Card>
        </div>

        {/* Right Column: Security & Metrics */}
        <div className="space-y-6">
          <Card className="border-primary/20 bg-primary/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-primary" />
                BYOK Security Architecture
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-muted-foreground">
              <p>
                • Personal keys are encrypted with <strong>AES-256-GCM</strong> using your unique deployment key before database storage.
              </p>
              <p>
                • Keys are decrypted strictly in-memory during execution and never written to application logs or client responses.
              </p>
              <p>
                • Multi-tenant database isolation ensures only your account can invoke or inspect your configured keys.
              </p>
            </CardContent>
          </Card>

          {/* Usage Totals */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-primary" />
                Token & Spend Summary
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <div className="flex items-center justify-between pb-2 border-b border-border">
                <span className="text-muted-foreground">Total Invocations:</span>
                <span className="font-semibold text-foreground">{usageRecords.length}</span>
              </div>
              <div className="flex items-center justify-between pb-2 border-b border-border">
                <span className="text-muted-foreground">Input Tokens:</span>
                <span className="font-mono text-foreground">{totalInputTokens.toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between pb-2 border-b border-border">
                <span className="text-muted-foreground">Output Tokens:</span>
                <span className="font-mono text-foreground">{totalOutputTokens.toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between pt-1">
                <span className="text-muted-foreground">Estimated Cost:</span>
                <span className="font-semibold text-emerald-600 text-sm">
                  {formatCurrency(totalEstimatedCost)}
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Historical LLM Usage Records Table (Collapsible - Collapsed by Default) */}
      <Card className="overflow-hidden">
        <CardHeader
          className="pb-3 cursor-pointer select-none hover:bg-muted/30 transition-colors"
          role="button"
          tabIndex={0}
          aria-expanded={isAuditExpanded}
          aria-controls="audit-history-section"
          id="btn-toggle-audit-history"
          onClick={() => setIsAuditExpanded(!isAuditExpanded)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setIsAuditExpanded(!isAuditExpanded);
            }
          }}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-1 rounded bg-muted/60 text-muted-foreground shrink-0">
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform duration-200",
                    isAuditExpanded ? "rotate-0" : "-rotate-90"
                  )}
                />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Layers className="h-4 w-4 text-primary" />
                  Recent LLM Generation Audit History
                  {usageRecords.length > 0 && (
                    <Badge variant="secondary" className="text-[10px] font-normal ml-1">
                      {usageRecords.length} {usageRecords.length === 1 ? "record" : "records"}
                    </Badge>
                  )}
                </CardTitle>
                <CardDescription className="text-xs mt-0.5">
                  {isAuditExpanded
                    ? "Detailed execution telemetry, tokens consumed, latency, and estimated model costs."
                    : "Click to expand audit trail and generation telemetry."}
                </CardDescription>
              </div>
            </div>

            <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
              <Button
                variant="ghost"
                size="xs"
                onClick={(e) => {
                  e.stopPropagation();
                  refetchUsage();
                }}
                disabled={isUsageRefetching}
                title="Refresh audit history"
                className="text-xs h-7 px-2.5 text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className={cn("h-3 w-3 mr-1", isUsageRefetching && "animate-spin")} />
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>

        {isAuditExpanded && (
          <CardContent id="audit-history-section" className="pt-0">
            {isUsageLoading ? (
              <div className="space-y-3 pt-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            ) : usageRecords.length === 0 ? (
              <div className="py-8 text-center text-xs text-muted-foreground border border-dashed border-border rounded-lg">
                No LLM requests recorded yet. Workflow runs will automatically track token usage and latency here.
              </div>
            ) : (
              <div className="rounded-lg border border-border overflow-hidden bg-card mt-1">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-muted/50 text-[11px] uppercase font-medium text-muted-foreground border-b border-border">
                      <tr>
                        <th className="py-2.5 px-3.5">Provider / Model</th>
                        <th className="py-2.5 px-3.5">Tokens (In / Out / Total)</th>
                        <th className="py-2.5 px-3.5">Latency</th>
                        <th className="py-2.5 px-3.5">Estimated Cost</th>
                        <th className="py-2.5 px-3.5">Status</th>
                        <th className="py-2.5 px-3.5">Timestamp</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {usageRecords.map((rec) => (
                        <tr key={rec.id} className="hover:bg-muted/30 transition-colors">
                          <td className="py-2.5 px-3.5">
                            <div className="font-medium text-foreground capitalize">{rec.provider}</div>
                            <div className="font-mono text-[11px] text-muted-foreground">{rec.model_id}</div>
                          </td>
                          <td className="py-2.5 px-3.5 font-mono text-[11px] text-muted-foreground">
                            {rec.input_tokens.toLocaleString()} / {rec.output_tokens.toLocaleString()} /{" "}
                            <strong className="text-foreground">{rec.total_tokens.toLocaleString()}</strong>
                          </td>
                          <td className="py-2.5 px-3.5 font-mono text-muted-foreground">
                            {rec.latency_ms} ms
                          </td>
                          <td className="py-2.5 px-3.5 font-medium text-[#16866B]">
                            {rec.estimated_cost ? formatCurrency(Number(rec.estimated_cost)) : "$0.0000"}
                          </td>
                          <td className="py-2.5 px-3.5">
                            <Badge
                              variant={rec.status === "success" ? "success" : "destructive"}
                              className="text-[10px]"
                            >
                              {rec.status}
                            </Badge>
                          </td>
                          <td className="py-2.5 px-3.5 text-muted-foreground">
                            {formatDate(rec.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* Delete Confirmation Modal */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-rose-600">
              <Trash2 className="h-5 w-5" />
              Remove Personal API Key
            </DialogTitle>
            <DialogDescription>
              Are you sure you want to remove your {deleteTarget?.provider.toUpperCase()} API key?
              Any workflows relying on this provider will fail until a new key is connected.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeleteTarget(null)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Removing..." : "Confirm Removal"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
