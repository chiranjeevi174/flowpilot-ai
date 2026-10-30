"use client";

import React, { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/auth-context";
import { Sidebar } from "@/components/layout/sidebar";
import { TopNav } from "@/components/layout/top-nav";
import { GlobalNotificationBanner } from "@/components/notifications/global-notification-banner";

function WorkspaceSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="flex items-center justify-between pb-2 border-b border-border/40">
        <div className="space-y-2">
          <div className="h-6 w-48 bg-muted/60 rounded-md" />
          <div className="h-3.5 w-80 bg-muted/40 rounded-md" />
        </div>
        <div className="h-8 w-28 bg-muted/50 rounded-md" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 bg-muted/30 rounded-lg border border-border/40" />
        ))}
      </div>
      <div className="h-64 bg-muted/20 rounded-lg border border-border/40" />
    </div>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      router.push("/login");
    }
  }, [user, isLoading, router]);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Live Global Workflow Countdown & Approval Banners */}
      <GlobalNotificationBanner />

      {/* Desktop Sidebar wrapped in Suspense for usePathname compatibility */}
      <Suspense fallback={<aside className="hidden md:flex w-64 border-r border-[#22313A] shrink-0 bg-[#172229]" />}>
        <Sidebar className="hidden md:flex" />
      </Suspense>

      {/* Main Content Workspace */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        <TopNav />
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-7">
          <div className="mx-auto max-w-7xl space-y-6 min-w-0">
            <Suspense fallback={<WorkspaceSkeleton />}>
              {children}
            </Suspense>
          </div>
        </main>
      </div>
    </div>
  );
}
