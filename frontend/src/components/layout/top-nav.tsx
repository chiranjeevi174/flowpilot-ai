"use client";

import React, { useState } from "react";
import Link from "next/link";
import { LogOut, Menu, User, Shield, X } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { ThemeToggle } from "./theme-toggle";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { Button } from "@/components/ui/button";
import { Sidebar } from "./sidebar";

export function TopNav() {
  const { user, logout } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);

  return (
    <>
      <header className="sticky top-0 z-40 flex h-14 w-full items-center justify-between border-b border-[#365650] bg-[#24433F] px-4 md:px-6 shadow-xs select-none">
        {/* Left: Mobile Toggle & FlowPilot Workspace Title */}
        <div className="flex items-center gap-3 min-w-0">
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden text-[#C3D5D0] hover:text-[#F5F8F6] hover:bg-[#30534D]"
            onClick={() => setMobileMenuOpen(true)}
            aria-label="Open navigation menu"
          >
            <Menu className="h-4 w-4" />
          </Button>

          <div className="flex items-center gap-2.5 truncate">
            <span className="font-semibold text-[#F5F8F6] text-xs md:text-sm tracking-tight truncate">
              Operations Workspace
            </span>
            <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-medium bg-[#1F3A36] text-[#66C4AE] border border-[#365650] shrink-0">
              <span className="h-1.5 w-1.5 rounded-full bg-[#66C4AE] animate-pulse" />
              Multi-Agent Engine
            </span>
          </div>
        </div>

        {/* Right: Actions, Theme, and Profile */}
        <div className="flex items-center gap-2.5 shrink-0">
          <NotificationBell />
          <ThemeToggle className="text-[#C3D5D0] hover:text-[#F5F8F6] hover:bg-[#30534D]" />

          {/* User Account Menu */}
          <div className="relative">
            <button
              onClick={() => setUserDropdownOpen(!userDropdownOpen)}
              className="flex items-center gap-2.5 p-1 rounded-lg hover:bg-[#30534D] transition-colors cursor-pointer focus:outline-none focus:ring-1.5 focus:ring-[#66C4AE]"
              aria-label="User profile menu"
              aria-expanded={userDropdownOpen}
            >
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#1F3A36] text-[#66C4AE] font-semibold text-xs border border-[#365650] shrink-0">
                {user?.full_name ? user.full_name.charAt(0).toUpperCase() : user?.email?.charAt(0).toUpperCase() || "U"}
              </div>
              <div className="hidden md:flex flex-col text-left max-w-[150px]">
                <span className="text-xs font-semibold leading-tight text-[#F5F8F6] truncate">
                  {user?.full_name || "Operator"}
                </span>
                <span className="text-[10px] text-[#C3D5D0] truncate">
                  {user?.email}
                </span>
              </div>
            </button>

            {/* Dropdown Menu */}
            {userDropdownOpen && (
              <>
                <div
                  className="fixed inset-0 z-[55]"
                  onClick={() => setUserDropdownOpen(false)}
                />
                <div className="absolute right-0 mt-1.5 w-56 rounded-lg border border-border bg-card p-1 text-card-foreground shadow-lg z-[60] animate-in fade-in-0 zoom-in-95">
                  <div className="px-3 py-2 border-b border-border/70 mb-1">
                    <p className="text-xs font-semibold text-foreground truncate">
                      {user?.full_name || "FlowPilot Operator"}
                    </p>
                    <p className="text-[11px] text-muted-foreground truncate font-mono">
                      {user?.email}
                    </p>
                  </div>
                  <Link
                    href="/settings/profile"
                    prefetch={true}
                    onClick={() => setUserDropdownOpen(false)}
                    className="flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-md text-foreground hover:bg-muted transition-colors"
                  >
                    <User className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>Profile & Password</span>
                  </Link>
                  <Link
                    href="/settings/llm"
                    prefetch={true}
                    onClick={() => setUserDropdownOpen(false)}
                    className="flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-md text-foreground hover:bg-muted transition-colors"
                  >
                    <Shield className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>BYOK LLM Providers</span>
                  </Link>
                  <div className="border-t border-border/70 my-1" />
                  <button
                    onClick={() => {
                      setUserDropdownOpen(false);
                      logout();
                    }}
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs rounded-md text-[#C44949] hover:bg-[#C44949]/10 transition-colors cursor-pointer text-left"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Mobile Navigation Drawer */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden" role="dialog" aria-modal="true">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileMenuOpen(false)}
          />
          <div className="relative z-50 flex w-72 flex-col bg-[#172229] shadow-2xl h-full">
            <div className="absolute top-3 right-3 z-10">
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-[#A9BABD] hover:text-[#FFFFFF] hover:bg-[#202D36]"
                onClick={() => setMobileMenuOpen(false)}
                aria-label="Close navigation"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <Sidebar className="w-full h-full border-r-0" />
          </div>
        </div>
      )}
    </>
  );
}
