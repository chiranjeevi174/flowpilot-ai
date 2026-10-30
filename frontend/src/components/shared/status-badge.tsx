import React from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  HelpCircle,
  Loader2,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AgentRunStatus } from "@/types";

interface StatusBadgeProps {
  status: AgentRunStatus | string;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalized = (status || "").toLowerCase();

  switch (normalized) {
    case "completed":
    case "active":
    case "succeeded":
    case "success":
      return (
        <Badge variant="success" className={className}>
          <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
          {status}
        </Badge>
      );

    case "running":
    case "executing":
      return (
        <Badge variant="info" className={className}>
          <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          {status}
        </Badge>
      );

    case "queued":
    case "pending":
      return (
        <Badge variant="secondary" className={className}>
          <Clock className="mr-1 h-3.5 w-3.5" />
          {status}
        </Badge>
      );

    case "awaiting_approval":
      return (
        <Badge variant="warning" className={className}>
          <AlertTriangle className="mr-1 h-3.5 w-3.5" />
          Awaiting Approval
        </Badge>
      );

    case "failed":
    case "error":
      return (
        <Badge variant="destructive" className={className}>
          <AlertCircle className="mr-1 h-3.5 w-3.5" />
          {status}
        </Badge>
      );

    case "cancelled":
    case "revoked":
    case "expired":
      return (
        <Badge variant="outline" className={className}>
          <XCircle className="mr-1 h-3.5 w-3.5" />
          {status}
        </Badge>
      );

    default:
      return (
        <Badge variant="outline" className={className}>
          <HelpCircle className="mr-1 h-3.5 w-3.5" />
          {status}
        </Badge>
      );
  }
}
