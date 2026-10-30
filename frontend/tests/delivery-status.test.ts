import { describe, it, expect } from "vitest";
import { getDeliveryStatusMeta } from "@/lib/delivery-status";

describe("getDeliveryStatusMeta", () => {
  it("renders Gmail successful action correctly without Meta queue terminology", () => {
    const action = {
      operation: "gmail_send_message",
      status: "succeeded",
      provider_response: { message_id: "18a12345678" },
    };

    const meta = getDeliveryStatusMeta(action);

    expect(meta.provider).toBe("gmail");
    expect(meta.isGmail).toBe(true);
    expect(meta.isWhatsApp).toBe(false);
    expect(meta.badgeLabel).toBe("Dispatched via Gmail");
    expect(meta.confirmedDeliveryText).toBe("GMAIL API ACCEPTED");
    expect(meta.badgeVariant).toBe("success");
    expect(meta.showSandboxWarning).toBeFalsy();
    // Critical verification: must NEVER mention Meta Queue
    expect(meta.confirmedDeliveryText).not.toContain("Meta");
    expect(meta.confirmedDeliveryText).not.toContain("Queue");
    expect(meta.badgeLabel).not.toContain("Meta");
  });

  it("renders send_email alias as Gmail without Meta terminology", () => {
    const action = {
      operation: "send_email",
      status: "succeeded",
      provider_response: { sent: true },
    };

    const meta = getDeliveryStatusMeta(action);

    expect(meta.isGmail).toBe(true);
    expect(meta.confirmedDeliveryText).toBe("GMAIL API ACCEPTED");
    expect(meta.confirmedDeliveryText).not.toContain("Meta");
  });

  it("renders Gmail failed action correctly", () => {
    const action = {
      operation: "gmail_send_message",
      status: "failed",
      error_message: "Token has expired or was revoked",
    };

    const meta = getDeliveryStatusMeta(action);

    expect(meta.provider).toBe("gmail");
    expect(meta.badgeVariant).toBe("destructive");
    expect(meta.badgeLabel).toBe("Gmail Send Failed");
    expect(meta.confirmedDeliveryText).toBe("SEND FAILED");
  });

  it("renders WhatsApp accepted status with sandbox notice and Meta queue terminology", () => {
    const action = {
      operation: "whatsapp_send_template",
      status: "succeeded",
      provider_response: {
        status: "accepted",
        message_id: "wamid.12345",
      },
    };

    const meta = getDeliveryStatusMeta(action);

    expect(meta.provider).toBe("whatsapp");
    expect(meta.isWhatsApp).toBe(true);
    expect(meta.badgeVariant).toBe("warning");
    expect(meta.badgeLabel).toBe("Accepted by API (Delivery Pending)");
    expect(meta.confirmedDeliveryText).toBe("PENDING (In Meta Queue)");
    expect(meta.showSandboxWarning).toBe(true);
  });

  it("renders WhatsApp delivered status accurately", () => {
    const action = {
      operation: "whatsapp_send_template",
      status: "succeeded",
      provider_response: {
        delivery_status: "delivered",
        message_id: "wamid.12345",
      },
    };

    const meta = getDeliveryStatusMeta(action);

    expect(meta.provider).toBe("whatsapp");
    expect(meta.badgeVariant).toBe("success");
    expect(meta.badgeLabel).toBe("Delivered to Device");
    expect(meta.confirmedDeliveryText).toBe("DELIVERED");
    expect(meta.isPending).toBe(false);
  });

  it("renders WhatsApp failed status with delivery error details", () => {
    const action = {
      operation: "whatsapp_send_template",
      status: "failed",
      provider_response: {
        delivery_status: "failed",
        delivery_errors: [{ code: 131030, title: "Recipient phone number not in allowed list" }],
      },
      error_message: "Recipient phone number not in allowed list",
    };

    const meta = getDeliveryStatusMeta(action);

    expect(meta.provider).toBe("whatsapp");
    expect(meta.badgeVariant).toBe("destructive");
    expect(meta.badgeLabel).toBe("Delivery Failed");
    expect(meta.deliveryErrors).toHaveLength(1);
    expect(meta.deliveryErrors?.[0].code).toBe(131030);
  });

  it("renders Slack and Google Sheets accurately", () => {
    const slackAction = { operation: "slack_post_message", status: "succeeded" };
    const sheetsAction = { operation: "sheets_append_row", status: "succeeded" };

    const slackMeta = getDeliveryStatusMeta(slackAction);
    const sheetsMeta = getDeliveryStatusMeta(sheetsAction);

    expect(slackMeta.badgeLabel).toBe("Posted to Slack");
    expect(slackMeta.confirmedDeliveryText).toBe("SLACK API ACCEPTED");

    expect(sheetsMeta.badgeLabel).toBe("Appended to Sheet");
    expect(sheetsMeta.confirmedDeliveryText).toBe("SHEETS API ACCEPTED");
  });
});
