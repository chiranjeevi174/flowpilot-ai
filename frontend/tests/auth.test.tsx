import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import LoginPage from "@/app/(auth)/login/page";
import RegisterPage from "@/app/(auth)/register/page";

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

// Mock AuthContext
const mockLogin = vi.fn();
const mockRegister = vi.fn();
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    user: null,
    isLoading: false,
    isAuthenticated: false,
    login: mockLogin,
    register: mockRegister,
  }),
}));

describe("Authentication Pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders login form correctly with password manager compatible attributes", () => {
    render(<LoginPage />);

    expect(screen.getByText("Welcome Back")).toBeInTheDocument();

    const emailInput = screen.getByLabelText(/Email Address/i);
    expect(emailInput).toBeInTheDocument();
    expect(emailInput).toHaveAttribute("type", "email");
    expect(emailInput).toHaveAttribute("name", "email");
    expect(emailInput).toHaveAttribute("id", "email");
    expect(emailInput).toHaveAttribute("autoComplete", "username");

    const passwordInput = screen.getByLabelText(/^Password/i);
    expect(passwordInput).toBeInTheDocument();
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toHaveAttribute("name", "password");
    expect(passwordInput).toHaveAttribute("id", "password");
    expect(passwordInput).toHaveAttribute("autoComplete", "current-password");

    expect(screen.getByRole("button", { name: /Sign In/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Forgot password\?/i })).toHaveAttribute(
      "href",
      "/forgot-password"
    );
  });

  it("validates empty email, invalid email format, and empty password", async () => {
    render(<LoginPage />);

    // 1. Empty email
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));
    expect(await screen.findByText("Please enter your email address.")).toBeInTheDocument();

    // 2. Invalid email format
    fireEvent.change(screen.getByLabelText(/Email Address/i), {
      target: { value: "invalid-email" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));
    expect(await screen.findByText("Please enter a valid email address.")).toBeInTheDocument();

    // 3. Empty password
    fireEvent.change(screen.getByLabelText(/Email Address/i), {
      target: { value: "valid@flowpilot.ai" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));
    expect(await screen.findByText("Please enter your password.")).toBeInTheDocument();
  });

  it("displays structured backend error codes for development and production", async () => {
    // 1. Unknown user
    const errorUserNotFound = new Error("Auth failed");
    (errorUserNotFound as any).data = {
      detail: "No account found with this email address.",
      error_code: "USER_NOT_FOUND",
    };
    mockLogin.mockRejectedValueOnce(errorUserNotFound);

    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText(/Email Address/i), {
      target: { value: "unknown@flowpilot.ai" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "Password123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));

    expect(
      await screen.findByText("No account found with this email address.")
    ).toBeInTheDocument();

    // 2. Incorrect password
    const errorWrongPassword = new Error("Auth failed");
    (errorWrongPassword as any).data = {
      detail: "Incorrect password. Please try again.",
      error_code: "INCORRECT_PASSWORD",
    };
    mockLogin.mockRejectedValueOnce(errorWrongPassword);

    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));
    expect(
      await screen.findByText("Incorrect password. Please try again.")
    ).toBeInTheDocument();

    // 3. Rate limited
    const errorRateLimited = new Error("Rate limited");
    (errorRateLimited as any).status = 429;
    (errorRateLimited as any).data = {
      detail: "Too many attempts. Please try again later.",
      error_code: "RATE_LIMITED",
    };
    mockLogin.mockRejectedValueOnce(errorRateLimited);

    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));
    expect(
      await screen.findByText("Too many attempts. Please try again later.")
    ).toBeInTheDocument();
  });

  it("submits login form with valid credentials", async () => {
    mockLogin.mockResolvedValueOnce(undefined);
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/Email Address/i), {
      target: { value: "operator@flowpilot.ai" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "SecureP@ss123" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        "operator@flowpilot.ai",
        "SecureP@ss123"
      );
      expect(mockPush).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("renders registration form with new-password autocomplete attributes", () => {
    render(<RegisterPage />);

    expect(screen.getByText("Create an Account")).toBeInTheDocument();
    expect(screen.getByLabelText(/Full Name/i)).toHaveAttribute("autoComplete", "name");
    expect(screen.getByLabelText(/Email Address/i)).toHaveAttribute("type", "email");

    const passInput = screen.getByLabelText(/^Password/i);
    expect(passInput).toHaveAttribute("autoComplete", "new-password");

    const confirmInput = screen.getByLabelText(/Confirm Password/i);
    expect(confirmInput).toHaveAttribute("autoComplete", "new-password");

    expect(screen.getByRole("button", { name: /Create Account/i })).toBeInTheDocument();
  });

  it("validates password matching during registration", async () => {
    render(<RegisterPage />);

    fireEvent.change(screen.getByLabelText(/Email Address/i), {
      target: { value: "operator@flowpilot.ai" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "SecurePassword123!" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), {
      target: { value: "DifferentPassword123!" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Create Account/i }));

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it("submits registration form on matching credentials", async () => {
    mockRegister.mockResolvedValueOnce(undefined);
    render(<RegisterPage />);

    fireEvent.change(screen.getByLabelText(/Full Name/i), {
      target: { value: "Jane Architect" },
    });
    fireEvent.change(screen.getByLabelText(/Email Address/i), {
      target: { value: "jane@flowpilot.ai" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "ComplexP@ssw0rd!" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), {
      target: { value: "ComplexP@ssw0rd!" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Create Account/i }));

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith(
        "jane@flowpilot.ai",
        "ComplexP@ssw0rd!",
        "Jane Architect"
      );
      expect(mockPush).toHaveBeenCalledWith("/dashboard");
    });
  });
});
