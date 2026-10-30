export type DeliveryBadgeVariant =
  | "success"
  | "warning"
  | "destructive"
  | "info"
  | "purple"
  | "secondary"
  | "outline";

export interface DeliveryStatusMeta {
  provider: "whatsapp" | "gmail" | "slack" | "sheets" | "external";
  badgeVariant: DeliveryBadgeVariant;
  badgeLabel: string;
  confirmedDeliveryText: string;
  dispatchResultText: string;
  isPending: boolean;
  isWhatsApp: boolean;
  isGmail: boolean;
  errorDetails?: string | null;
  deliveryErrors?: any[];
  showSandboxWarning?: boolean;
}

/**
 * Resolves provider-specific external action delivery status and presentation metadata.
 * Ensures Gmail actions NEVER display Meta WhatsApp queue terminology.
 */
export function getDeliveryStatusMeta(action: {
  operation?: string;
  status: string;
  error_message?: string | null;
  provider_response?: Record<string, any> | null;
}): DeliveryStatusMeta {
  const op = (action.operation || "").toLowerCase();
  const resp = action.provider_response || {};
  const deliveryStatus = (resp.delivery_status || "").toLowerCase();
  const deliveryErrors = resp.delivery_errors;

  // 1. WhatsApp Actions (Supports webhook delivery tracking: accepted, sent, delivered, read, failed)
  if (op.startsWith("whatsapp_")) {
    if (deliveryStatus === "read") {
      return {
        provider: "whatsapp",
        badgeVariant: "purple",
        badgeLabel: "Read by Recipient",
        confirmedDeliveryText: "READ",
        dispatchResultText: action.status === "succeeded" ? "Dispatched (HTTP 200 OK)" : action.status,
        isPending: false,
        isWhatsApp: true,
        isGmail: false,
      };
    }
    if (deliveryStatus === "delivered") {
      return {
        provider: "whatsapp",
        badgeVariant: "success",
        badgeLabel: "Delivered to Device",
        confirmedDeliveryText: "DELIVERED",
        dispatchResultText: action.status === "succeeded" ? "Dispatched (HTTP 200 OK)" : action.status,
        isPending: false,
        isWhatsApp: true,
        isGmail: false,
      };
    }
    if (deliveryStatus === "sent") {
      return {
        provider: "whatsapp",
        badgeVariant: "info",
        badgeLabel: "Sent (In Transit)",
        confirmedDeliveryText: "SENT (IN TRANSIT)",
        dispatchResultText: action.status === "succeeded" ? "Dispatched (HTTP 200 OK)" : action.status,
        isPending: true,
        isWhatsApp: true,
        isGmail: false,
      };
    }
    if (deliveryStatus === "failed" || action.status === "failed") {
      return {
        provider: "whatsapp",
        badgeVariant: "destructive",
        badgeLabel: "Delivery Failed",
        confirmedDeliveryText: "FAILED",
        dispatchResultText: "Failed",
        isPending: false,
        isWhatsApp: true,
        isGmail: false,
        errorDetails: action.error_message || "Message delivery failed downstream per Meta webhook.",
        deliveryErrors: Array.isArray(deliveryErrors) ? deliveryErrors : undefined,
      };
    }
    // Dispatched successfully to Meta API gateway, waiting for carrier status webhook
    return {
      provider: "whatsapp",
      badgeVariant: "warning",
      badgeLabel: "Accepted by API (Delivery Pending)",
      confirmedDeliveryText: "PENDING (In Meta Queue)",
      dispatchResultText: action.status === "succeeded" ? "Dispatched (HTTP 200 OK)" : action.status,
      isPending: true,
      isWhatsApp: true,
      isGmail: false,
      showSandboxWarning: true,
    };
  }

  // 2. Gmail Actions (Never display Meta-specific queue terminology!)
  if (op.startsWith("gmail_") || op === "send_email") {
    if (action.status === "failed") {
      return {
        provider: "gmail",
        badgeVariant: "destructive",
        badgeLabel: "Gmail Send Failed",
        confirmedDeliveryText: "SEND FAILED",
        dispatchResultText: "Failed",
        isPending: false,
        isWhatsApp: false,
        isGmail: true,
        errorDetails: action.error_message || "Gmail API rejected the dispatch request.",
      };
    }
    if (action.status === "executing") {
      return {
        provider: "gmail",
        badgeVariant: "warning",
        badgeLabel: "Dispatching via Gmail",
        confirmedDeliveryText: "SENDING IN PROGRESS",
        dispatchResultText: "Executing",
        isPending: true,
        isWhatsApp: false,
        isGmail: true,
      };
    }
    return {
      provider: "gmail",
      badgeVariant: "success",
      badgeLabel: "Dispatched via Gmail",
      confirmedDeliveryText: "GMAIL API ACCEPTED",
      dispatchResultText: "Dispatched (HTTP 200 OK)",
      isPending: false,
      isWhatsApp: false,
      isGmail: true,
    };
  }

  // 3. Slack Actions
  if (op.startsWith("slack_")) {
    if (action.status === "failed") {
      return {
        provider: "slack",
        badgeVariant: "destructive",
        badgeLabel: "Slack Post Failed",
        confirmedDeliveryText: "POST FAILED",
        dispatchResultText: "Failed",
        isPending: false,
        isWhatsApp: false,
        isGmail: false,
        errorDetails: action.error_message || "Slack API rejected the message post.",
      };
    }
    if (action.status === "executing") {
      return {
        provider: "slack",
        badgeVariant: "warning",
        badgeLabel: "Posting to Slack",
        confirmedDeliveryText: "POSTING IN PROGRESS",
        dispatchResultText: "Executing",
        isPending: true,
        isWhatsApp: false,
        isGmail: false,
      };
    }
    return {
      provider: "slack",
      badgeVariant: "success",
      badgeLabel: "Posted to Slack",
      confirmedDeliveryText: "SLACK API ACCEPTED",
      dispatchResultText: "Dispatched (HTTP 200 OK)",
      isPending: false,
      isWhatsApp: false,
      isGmail: false,
    };
  }

  // 4. Google Sheets Actions
  if (op.startsWith("sheets_")) {
    if (action.status === "failed") {
      return {
        provider: "sheets",
        badgeVariant: "destructive",
        badgeLabel: "Sheet Update Failed",
        confirmedDeliveryText: "UPDATE FAILED",
        dispatchResultText: "Failed",
        isPending: false,
        isWhatsApp: false,
        isGmail: false,
        errorDetails: action.error_message || "Google Sheets API rejected the update.",
      };
    }
    if (action.status === "executing") {
      return {
        provider: "sheets",
        badgeVariant: "warning",
        badgeLabel: "Updating Sheet",
        confirmedDeliveryText: "UPDATING IN PROGRESS",
        dispatchResultText: "Executing",
        isPending: true,
        isWhatsApp: false,
        isGmail: false,
      };
    }
    return {
      provider: "sheets",
      badgeVariant: "success",
      badgeLabel: "Appended to Sheet",
      confirmedDeliveryText: "SHEETS API ACCEPTED",
      dispatchResultText: "Dispatched (HTTP 200 OK)",
      isPending: false,
      isWhatsApp: false,
      isGmail: false,
    };
  }

  // 5. Generic / External Fallback
  if (action.status === "succeeded") {
    return {
      provider: "external",
      badgeVariant: "success",
      badgeLabel: "Dispatched",
      confirmedDeliveryText: "DISPATCHED",
      dispatchResultText: "Dispatched (HTTP 200 OK)",
      isPending: false,
      isWhatsApp: false,
      isGmail: false,
    };
  }
  if (action.status === "executing") {
    return {
      provider: "external",
      badgeVariant: "warning",
      badgeLabel: "Executing",
      confirmedDeliveryText: "IN PROGRESS",
      dispatchResultText: "Executing",
      isPending: true,
      isWhatsApp: false,
      isGmail: false,
    };
  }
  return {
    provider: "external",
    badgeVariant: "destructive",
    badgeLabel: "Failed",
    confirmedDeliveryText: "FAILED",
    dispatchResultText: "Failed",
    isPending: false,
    isWhatsApp: false,
    isGmail: false,
    errorDetails: action.error_message || "Action failed.",
  };
}
