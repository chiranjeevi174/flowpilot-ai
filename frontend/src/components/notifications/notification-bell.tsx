"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  Clock,
  ShieldAlert,
  Play,
  CheckCheck,
  ExternalLink,
  Laptop,
  Check,
} from "lucide-react";
import { useNotifications } from "@/lib/notifications/notification-context";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function NotificationBell() {
  const router = useRouter();
  const {
    notifications,
    unreadCount,
    markAsRead,
    markAllRead,
    browserPermission,
    requestBrowserPermission,
  } = useNotifications();

  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState<"all" | "schedule" | "approval">("all");

  const filteredNotifications = notifications.filter((notif) => {
    if (filter === "all") return true;
    return notif.category === filter;
  });

  const handleNotificationClick = async (notif: (typeof notifications)[0]) => {
    if (!notif.is_read) {
      await markAsRead(notif.id);
    }
    if (notif.link_url) {
      setIsOpen(false);
      router.push(notif.link_url);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative flex h-8 w-8 items-center justify-center rounded-lg text-[#C3D5D0] hover:text-[#F5F8F6] hover:bg-[#30534D] transition-colors focus:outline-none focus:ring-1.5 focus:ring-[#66C4AE] cursor-pointer"
        aria-label="View notifications"
        aria-expanded={isOpen}
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-[#087F72] text-[#F5F8F6] text-[10px] font-bold border border-[#24433F] shadow-xs animate-in zoom-in-75">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-xl border border-border bg-card p-0 text-card-foreground shadow-2xl z-50 animate-in fade-in-0 zoom-in-95 overflow-hidden">
            {/* Popover Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-foreground">Notifications</span>
                {unreadCount > 0 && (
                  <span className="px-1.5 py-0.5 text-[10px] font-semibold rounded-full bg-primary/15 text-primary">
                    {unreadCount} new
                  </span>
                )}
              </div>
              {unreadCount > 0 && (
                <button
                  onClick={() => markAllRead()}
                  className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                  title="Mark all as read"
                >
                  <CheckCheck className="h-3 w-3" />
                  <span>Mark all read</span>
                </button>
              )}
            </div>

            {/* Filter Tabs */}
            <div className="flex items-center gap-1 px-3 py-1.5 border-b border-border/70 bg-card text-[11px]">
              {(["all", "schedule", "approval"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setFilter(tab)}
                  className={`px-2.5 py-1 rounded-md font-medium transition-colors capitalize ${
                    filter === tab
                      ? "bg-primary/10 text-primary font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {tab === "all" ? "All" : tab === "schedule" ? "Schedules" : "Approvals"}
                </button>
              ))}
            </div>

            {/* Notification List */}
            <div className="max-h-80 overflow-y-auto divide-y divide-border/50">
              {filteredNotifications.length === 0 ? (
                <div className="py-8 text-center text-xs text-muted-foreground">
                  <Bell className="h-6 w-6 mx-auto mb-2 opacity-40" />
                  <p>No notifications to display</p>
                </div>
              ) : (
                filteredNotifications.map((notif) => {
                  const isApproval = notif.type === "approval_required" || notif.category === "approval";
                  const isSchedule = notif.type === "schedule_countdown" || notif.type === "workflow_started";

                  return (
                    <div
                      key={notif.id}
                      onClick={() => handleNotificationClick(notif)}
                      className={`p-3 text-xs transition-colors cursor-pointer flex items-start gap-2.5 hover:bg-muted/40 ${
                        !notif.is_read ? "bg-primary/5" : ""
                      }`}
                    >
                      <div className="mt-0.5 shrink-0">
                        {isApproval ? (
                          <div className="h-6 w-6 rounded-full bg-amber-500/15 text-amber-600 flex items-center justify-center">
                            <ShieldAlert className="h-3.5 w-3.5" />
                          </div>
                        ) : isSchedule ? (
                          <div className="h-6 w-6 rounded-full bg-primary/15 text-primary flex items-center justify-center">
                            <Clock className="h-3.5 w-3.5" />
                          </div>
                        ) : (
                          <div className="h-6 w-6 rounded-full bg-muted text-muted-foreground flex items-center justify-center">
                            <Play className="h-3.5 w-3.5" />
                          </div>
                        )}
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-1">
                          <p className={`truncate font-medium text-xs ${!notif.is_read ? "text-foreground font-semibold" : "text-foreground/90"}`}>
                            {notif.title}
                          </p>
                          <span className="text-[10px] text-muted-foreground shrink-0 font-mono">
                            {formatDate(notif.created_at)}
                          </span>
                        </div>
                        <p className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">
                          {notif.message}
                        </p>

                        {/* Action buttons embedded */}
                        {notif.link_url && (
                          <div className="mt-2 flex items-center gap-2">
                            <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-primary hover:underline">
                              <span>Open details</span>
                              <ExternalLink className="h-2.5 w-2.5" />
                            </span>
                          </div>
                        )}
                      </div>

                      {!notif.is_read && (
                        <span className="h-2 w-2 rounded-full bg-primary shrink-0 mt-1.5" />
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* Desktop Notification Prompt Footer */}
            <div className="p-2.5 border-t border-border bg-muted/20 flex items-center justify-between text-[11px]">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Laptop className="h-3.5 w-3.5" />
                Browser alerts
              </span>
              {browserPermission === "granted" ? (
                <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-medium text-[10px]">
                  <Check className="h-3 w-3" />
                  Enabled
                </span>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-6 px-2 text-[10px]"
                  onClick={requestBrowserPermission}
                >
                  Enable desktop alerts
                </Button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
