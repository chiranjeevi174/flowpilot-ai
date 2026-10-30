"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarClock,
  CheckSquare,
  Cpu,
  Layers,
  LayoutDashboard,
  ListTree,
  Plug,
  Sparkles,
  User,
  Workflow,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}

const workflowNavItems: NavItem[] = [
  { name: "Overview", href: "/dashboard", icon: LayoutDashboard },
  { name: "New Workflow", href: "/workflows", icon: Sparkles },
  { name: "Executions", href: "/executions", icon: ListTree },
  { name: "Approvals", href: "/approvals", icon: CheckSquare },
  { name: "Schedules", href: "/schedules", icon: CalendarClock },
  { name: "Integrations", href: "/integrations", icon: Layers },
];

const configNavItems: NavItem[] = [
  { name: "Multi-LLM (BYOK)", href: "/settings/llm", icon: Cpu },
  { name: "App Connections", href: "/settings/connections", icon: Plug },
  { name: "Account Profile", href: "/settings/profile", icon: User },
];

export function Sidebar({ className }: { className?: string }) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex flex-col w-64 border-r border-[#22313A] bg-[#172229] text-[#F1F5F5] p-3.5 shrink-0 transition-colors select-none",
        className
      )}
    >
      {/* Brand Header */}
      <div className="flex items-center gap-3 px-2 py-3.5 mb-3 border-b border-[#22313A]">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#087F72]/20 border border-[#087F72]/40 text-[#087F72] shadow-xs shrink-0">
          <Workflow className="h-4 w-4 text-[#087F72]" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-sm tracking-tight text-[#F1F5F5]">
              FlowPilot
            </span>
            <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-[#087F72] text-white">
              AI
            </span>
          </div>
          <span className="block text-[10px] text-[#A9BABD] font-medium tracking-tight truncate">
            Enterprise Multi-Agent
          </span>
        </div>
      </div>

      {/* Navigation Sections */}
      <div className="flex-1 space-y-5 overflow-y-auto pr-1">
        <div>
          <div className="px-2.5 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#A9BABD]/70">
            Workflows
          </div>
          <nav className="space-y-0.5" aria-label="Workflow Navigation">
            {workflowNavItems.map((item) => {
              const isActive =
                item.href === "/dashboard"
                  ? pathname === "/dashboard"
                  : pathname?.startsWith(item.href);
              const Icon = item.icon;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={true}
                  className={cn(
                    "flex items-center gap-2.5 px-2.5 py-2 rounded-md text-xs font-medium transition-all group",
                    isActive
                      ? "bg-[#23423F] text-[#FFFFFF] font-semibold border-l-2 border-[#087F72] shadow-xs pl-2"
                      : "text-[#A9BABD] hover:bg-[#202D36] hover:text-[#FFFFFF]"
                  )}
                  aria-current={isActive ? "page" : undefined}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0 transition-colors",
                      isActive
                        ? "text-[#087F72] dark:text-[#2DD4BF]"
                        : "text-[#A9BABD] group-hover:text-[#FFFFFF]"
                    )}
                  />
                  <span className="truncate">{item.name}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        <div>
          <div className="px-2.5 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#A9BABD]/70">
            Configuration
          </div>
          <nav className="space-y-0.5" aria-label="Configuration Navigation">
            {configNavItems.map((item) => {
              const isActive = pathname?.startsWith(item.href);
              const Icon = item.icon;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={true}
                  className={cn(
                    "flex items-center gap-2.5 px-2.5 py-2 rounded-md text-xs font-medium transition-all group",
                    isActive
                      ? "bg-[#23423F] text-[#FFFFFF] font-semibold border-l-2 border-[#087F72] shadow-xs pl-2"
                      : "text-[#A9BABD] hover:bg-[#202D36] hover:text-[#FFFFFF]"
                  )}
                  aria-current={isActive ? "page" : undefined}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0 transition-colors",
                      isActive
                        ? "text-[#087F72] dark:text-[#2DD4BF]"
                        : "text-[#A9BABD] group-hover:text-[#FFFFFF]"
                    )}
                  />
                  <span className="truncate">{item.name}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Engine Status Footer */}
      <div className="pt-3 border-t border-[#22313A] px-2.5 mt-auto">
        <div className="flex items-center justify-between text-[11px] text-[#A9BABD]">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#16866B] opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[#16866B]" />
            </span>
            <span className="font-mono text-[10px]">LangGraph v0.1</span>
          </div>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#202D36] text-[#A9BABD] font-medium">
            Active
          </span>
        </div>
      </div>
    </aside>
  );
}
