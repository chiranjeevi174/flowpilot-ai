"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Cpu,
  Lightbulb,
  Play,
  Sparkles,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const promptTemplates = [
  {
    title: "Weekly Ops Briefing",
    prompt:
      "Fetch system health metrics from monitoring, summarize agent activity, and post an executive summary to Slack.",
    tag: "Slack & Health",
  },
  {
    title: "Lead Enrichment Pipeline",
    prompt:
      "Read new leads from Google Sheets, verify email deliverability, and prepare personalized outreach drafts.",
    tag: "Sheets & Gmail",
  },
  {
    title: "Customer Support & Email Drafting",
    prompt:
      "Review the recent customer inquiries regarding service degradation, summarize key pain points, and prepare a polite, professional resolution email.",
    tag: "Gmail & NLP",
  },
];

export function WorkflowsClient() {
  const router = useRouter();
  const [requestText, setRequestText] = useState("");
  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch connected LLM credentials
  const { data: credentials } = useQuery({
    queryKey: ["llm", "credentials"],
    queryFn: () => api.llm.listCredentials(),
  });

  // Fetch available models if provider selected
  const { data: modelDiscovery } = useQuery({
    queryKey: ["llm", "models", selectedProvider],
    queryFn: () => api.llm.discoverModels(selectedProvider || undefined),
    enabled: !!selectedProvider,
  });

  const discoveredModels = Array.isArray(modelDiscovery)
    ? modelDiscovery
    : (modelDiscovery as any)?.models || [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Guard against duplicate submissions while request is in flight
    if (isSubmitting) return;

    if (!requestText.trim() || requestText.trim().length < 5) {
      toast.error("Please enter a descriptive workflow instruction (minimum 5 characters).");
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: { request: string; provider?: string; model?: string } = {
        request: requestText.trim(),
      };
      if (selectedProvider) payload.provider = selectedProvider;
      if (selectedModel) payload.model = selectedModel;

      const run = await api.workflows.createRun(payload);
      toast.success("Workflow execution initiated (HTTP 202 Accepted)");
      // Release submission state before or during navigation
      setIsSubmitting(false);
      router.push(`/executions/${run.id}`);
    } catch (err: any) {
      toast.error(err.message || "Failed to initiate workflow execution.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-8 max-w-5xl">
      <PageHeader
        title="New Workflow Execution"
        description="Describe what you want the multi-agent system to accomplish in natural language. Intent, planning, and verification agents will coordinate execution."
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Workflow Creation Form */}
        <div className="lg:col-span-2 space-y-6">
          <Card className="border-border shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-primary" />
                Instruction & Objective
              </CardTitle>
              <CardDescription>
                State what tasks, external tools, or analysis you want the agents to execute.
              </CardDescription>
            </CardHeader>

            <form onSubmit={handleSubmit}>
              <CardContent className="space-y-5">
                <div className="space-y-2">
                  <Textarea
                    placeholder="Describe what you want the multi-agent system to accomplish (e.g. Read the latest spreadsheet data, analyze metrics, and prepare an email response)..."
                    value={requestText}
                    onChange={(e) => setRequestText(e.target.value)}
                    className="min-h-[160px] text-base leading-relaxed"
                    required
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>Be specific about external recipients, sheets, or channels.</span>
                    <span>{requestText.length} characters</span>
                  </div>
                </div>

                {/* Optional Provider Override */}
                <div className="pt-2 border-t border-border/60">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
                    <Cpu className="h-3.5 w-3.5" />
                    Model Override (Optional)
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs font-medium text-foreground mb-1 block">
                        Provider
                      </label>
                      <Select
                        value={selectedProvider}
                        onChange={(e) => {
                          setSelectedProvider(e.target.value);
                          setSelectedModel("");
                        }}
                      >
                        <option value="">Default Preference</option>
                        {(credentials || []).map((cred) => (
                          <option key={cred.id} value={cred.provider}>
                            {cred.provider.toUpperCase()} ({cred.key_fingerprint.slice(0, 8)}...)
                          </option>
                        ))}
                      </Select>
                    </div>

                    <div>
                      <label className="text-xs font-medium text-foreground mb-1 block">
                        Model
                      </label>
                      <Select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        disabled={!selectedProvider || discoveredModels.length === 0}
                      >
                        <option value="">Default Provider Model</option>
                        {discoveredModels.map((m: any) => (
                          <option key={m.id} value={m.id}>
                            {m.name || m.id}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </div>
                </div>
              </CardContent>

              <CardFooter className="pt-4 flex justify-between items-center border-t border-border/60">
                <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                  <Zap className="h-3.5 w-3.5 text-primary" />
                  <span>Durable Celery asynchronous dispatch</span>
                </span>
                <Button
                  type="submit"
                  isLoading={isSubmitting}
                  className="px-5 h-9 text-xs font-medium shadow-xs"
                >
                  <Play className="mr-1.5 h-3.5 w-3.5 fill-current" />
                  Execute Workflow
                </Button>
              </CardFooter>
            </form>
          </Card>
        </div>

        {/* Quick Preset Templates */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-[#B7791F]" />
            <h3 className="font-semibold text-xs text-foreground uppercase tracking-wider">Example Templates</h3>
          </div>
          <div className="space-y-3">
            {promptTemplates.map((template, idx) => (
              <div
                key={idx}
                onClick={() => setRequestText(template.prompt)}
                className="p-4 rounded-xl border border-border bg-card hover:border-primary/40 hover:shadow-xs cursor-pointer transition-all group"
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-semibold text-xs text-foreground group-hover:text-primary transition-colors">
                    {template.title}
                  </span>
                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-primary/10 text-primary border border-primary/20">
                    {template.tag}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                  {template.prompt}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
