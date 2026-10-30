import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { TopNav } from "@/components/layout/top-nav";

const mockLogout = vi.fn();

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      email: "operator@example.com",
      full_name: "Lead Operator",
      is_active: true,
    },
    logout: mockLogout,
    isLoading: false,
  }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme: "light",
    setTheme: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: vi.fn() }),
}));

describe("TopNav Component — Enterprise Deep Teal-Slate Header", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with header background tokens and workspace title", () => {
    const { container } = render(<TopNav />);

    const header = container.querySelector("header");
    expect(header).toBeInTheDocument();
    expect(header?.className).toContain("bg-[#24433F]");
    expect(header?.className).toContain("border-[#365650]");

    expect(screen.getByText("Operations Workspace")).toBeInTheDocument();
    expect(screen.getByText("Multi-Agent Engine")).toBeInTheDocument();
  });

  it("renders user profile trigger and opens dropdown on click", () => {
    render(<TopNav />);

    const userButton = screen.getByRole("button", { name: /User profile menu/i });
    expect(userButton).toBeInTheDocument();
    expect(userButton).toHaveAttribute("aria-expanded", "false");

    // Click to open dropdown
    fireEvent.click(userButton);
    expect(userButton).toHaveAttribute("aria-expanded", "true");

    // Menu options should be visible
    expect(screen.getByText("Profile & Password")).toBeInTheDocument();
    expect(screen.getByText("BYOK LLM Providers")).toBeInTheDocument();
    expect(screen.getByText("Sign Out")).toBeInTheDocument();

    // Click Sign Out
    const signOutBtn = screen.getByText("Sign Out");
    fireEvent.click(signOutBtn);
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });
});
