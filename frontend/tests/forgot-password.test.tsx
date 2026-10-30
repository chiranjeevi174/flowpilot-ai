import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import ForgotPasswordPage from "@/app/(auth)/forgot-password/page";
import ResetPasswordPage from "@/app/(auth)/reset-password/page";
import { api } from "@/lib/api/client";

// Mock next/navigation
const mockPush = vi.fn();
let mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
  }),
  useSearchParams: () => mockSearchParams,
}));

// Mock API client
vi.mock("@/lib/api/client", () => ({
  api: {
    auth: {
      forgotPassword: vi.fn(),
      validateResetToken: vi.fn(),
      resetPassword: vi.fn(),
    },
  },
}));

describe("Forgot & Reset Password Pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams();
  });

  describe("ForgotPasswordPage", () => {
    it("renders forgot password form with proper attributes", () => {
      render(<ForgotPasswordPage />);

      expect(screen.getByText("Reset Your Password")).toBeInTheDocument();
      const emailInput = screen.getByLabelText(/Email Address/i);
      expect(emailInput).toBeInTheDocument();
      expect(emailInput).toHaveAttribute("type", "email");
      expect(emailInput).toHaveAttribute("name", "email");
      expect(emailInput).toHaveAttribute("autoComplete", "username");
      expect(screen.getByRole("button", { name: /Send Recovery Link/i })).toBeInTheDocument();
    });

    it("validates empty and invalid email", async () => {
      render(<ForgotPasswordPage />);

      // Empty submit
      fireEvent.click(screen.getByRole("button", { name: /Send Recovery Link/i }));
      expect(await screen.findByText("Please enter your email address.")).toBeInTheDocument();

      // Invalid format
      fireEvent.change(screen.getByLabelText(/Email Address/i), {
        target: { value: "invalid-email" },
      });
      fireEvent.click(screen.getByRole("button", { name: /Send Recovery Link/i }));
      expect(await screen.findByText("Please enter a valid email address.")).toBeInTheDocument();
    });

    it("submits recovery request and renders success confirmation", async () => {
      vi.mocked(api.auth.forgotPassword).mockResolvedValueOnce({
        message: "Instructions sent",
        email_sent: false,
        dev_reset_url: "http://localhost:3000/reset-password?token=secret123",
      });

      render(<ForgotPasswordPage />);

      fireEvent.change(screen.getByLabelText(/Email Address/i), {
        target: { value: "operator@flowpilot.ai" },
      });
      fireEvent.click(screen.getByRole("button", { name: /Send Recovery Link/i }));

      await waitFor(() => {
        expect(api.auth.forgotPassword).toHaveBeenCalledWith({
          email: "operator@flowpilot.ai",
        });
      });

      expect(await screen.findByText("Recovery Request Received")).toBeInTheDocument();
      expect(screen.getByText(/Development Mode Link:/i)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Return to Sign In/i })).toBeInTheDocument();
    });
  });

  describe("ResetPasswordPage", () => {
    it("shows error when no token is present in search parameters", async () => {
      mockSearchParams = new URLSearchParams("");
      render(<ResetPasswordPage />);

      expect(await screen.findByText("Invalid or Expired Link")).toBeInTheDocument();
      expect(
        screen.getByText(/No reset token provided/i)
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Request a New Reset Link/i })
      ).toBeInTheDocument();
    });

    it("validates invalid or expired token against the API", async () => {
      mockSearchParams = new URLSearchParams("token=expired_token_123");
      vi.mocked(api.auth.validateResetToken).mockResolvedValueOnce({
        valid: false,
        reason: "This password reset link has expired.",
      });

      render(<ResetPasswordPage />);

      expect(await screen.findByText("Invalid or Expired Link")).toBeInTheDocument();
      expect(
        screen.getByText("This password reset link has expired.")
      ).toBeInTheDocument();
    });

    it("renders reset password form when token is valid and submits successfully", async () => {
      mockSearchParams = new URLSearchParams("token=valid_token_xyz");
      vi.mocked(api.auth.validateResetToken).mockResolvedValueOnce({
        valid: true,
        email: "operator@flowpilot.ai",
      });
      vi.mocked(api.auth.resetPassword).mockResolvedValueOnce({
        message: "Password has been reset successfully.",
      });

      render(<ResetPasswordPage />);

      expect(
        await screen.findByText(/Choose a strong password for operator@flowpilot.ai/i)
      ).toBeInTheDocument();

      const newPassInput = screen.getByLabelText(/^New Password/i);
      expect(newPassInput).toHaveAttribute("autoComplete", "new-password");

      const confirmPassInput = screen.getByLabelText(/Confirm New Password/i);
      expect(confirmPassInput).toHaveAttribute("autoComplete", "new-password");

      // Test password mismatch
      fireEvent.change(newPassInput, { target: { value: "NewSecurePassword123!" } });
      fireEvent.change(confirmPassInput, { target: { value: "MismatchPassword123!" } });
      fireEvent.click(screen.getByRole("button", { name: /Set New Password/i }));

      expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();

      // Test valid matching submission
      fireEvent.change(confirmPassInput, { target: { value: "NewSecurePassword123!" } });
      fireEvent.click(screen.getByRole("button", { name: /Set New Password/i }));

      await waitFor(() => {
        expect(api.auth.resetPassword).toHaveBeenCalledWith({
          token: "valid_token_xyz",
          password: "NewSecurePassword123!",
        });
      });

      expect(
        await screen.findByText("Password Changed Successfully")
      ).toBeInTheDocument();
    });
  });
});
