import React from "react";
import { Badge } from "@/components/ui/badge";
import { INTEGRATION_STATUS_MAP } from "@/lib/integrations-status";
import { Loader2 } from "lucide-react";

export interface IntegrationStatusBadgeProps {
  status: string;
  isVerifying?: boolean;
  className?: string;
  "data-testid"?: string;
}

/**
 * Accessible enterprise status badge for integration cards with text label and icon indicator.
 * Guarantees flex/shrink safety within responsive card boundaries.
 */
export function IntegrationStatusBadge({
  status,
  isVerifying = false,
  className = "",
  "data-testid": testId,
}: IntegrationStatusBadgeProps) {
  if (isVerifying) {
    const verifyingCfg = INTEGRATION_STATUS_MAP.verifying;
    return (
      <Badge
        variant="outline"
        data-testid={testId || "status-badge-verifying"}
        className={`text-xs px-2.5 py-0.5 font-medium inline-flex items-center gap-1.5 shrink-0 whitespace-nowrap border rounded-full transition-colors ${verifyingCfg.bg} ${verifyingCfg.text} ${verifyingCfg.border} ${className}`}
      >
        <Loader2 className="h-3 w-3 animate-spin shrink-0" aria-hidden="true" />
        <span>{verifyingCfg.label}</span>
      </Badge>
    );
  }

  const normalized = (status || "").toLowerCase().trim();
  const cfg =
    INTEGRATION_STATUS_MAP[normalized] || INTEGRATION_STATUS_MAP.not_configured;
  const Icon = cfg.icon;

  return (
    <Badge
      variant="outline"
      data-testid={testId || `status-badge-${normalized}`}
      className={`text-xs px-2.5 py-0.5 font-medium inline-flex items-center gap-1.5 shrink-0 whitespace-nowrap border rounded-full transition-colors ${cfg.bg} ${cfg.text} ${cfg.border} ${className}`}
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span>{cfg.label}</span>
    </Badge>
  );
}
