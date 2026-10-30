"use client";

import * as React from "react";
import { useMutation } from "@tanstack/react-query";
import {
  User as UserIcon,
  Mail,
  Lock,
  ShieldCheck,
  RefreshCw,
  Calendar,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth/auth-context";
import { api } from "@/lib/api/client";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

export default function ProfileSettingsPage() {
  const { user, refreshUser } = useAuth();

  // Name form state
  const [fullName, setFullName] = React.useState(user?.full_name || "");

  // Password form state
  const [newPassword, setNewPassword] = React.useState("");
  const [confirmPassword, setConfirmPassword] = React.useState("");

  React.useEffect(() => {
    if (user?.full_name) {
      setFullName(user.full_name);
    }
  }, [user]);

  const updateProfileMutation = useMutation({
    mutationFn: (body: { full_name?: string; password?: string }) =>
      api.auth.updateProfile(body),
    onSuccess: () => {
      toast.success("Profile updated successfully");
      refreshUser();
      setNewPassword("");
      setConfirmPassword("");
    },
    onError: (err: any) => {
      toast.error("Failed to update profile", {
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  const handleUpdateName = (e: React.FormEvent) => {
    e.preventDefault();
    updateProfileMutation.mutate({ full_name: fullName.trim() });
  };

  const handleUpdatePassword = (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 8) {
      toast.error("Password must be at least 8 characters long.");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("New passwords do not match.");
      return;
    }
    updateProfileMutation.mutate({ password: newPassword });
  };

  const initials = user?.full_name
    ? user.full_name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : user?.email.slice(0, 2).toUpperCase() || "FP";

  return (
    <div className="space-y-8 max-w-4xl">
      <PageHeader
        title="Account & Security Settings"
        description="Manage your profile information, password credentials, and authentication security."
      />

      {/* Profile Overview Card */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col sm:flex-row items-center gap-6">
            <div className="h-20 w-20 rounded-full bg-primary/10 border-2 border-primary/20 flex items-center justify-center text-xl font-bold text-primary shrink-0">
              {initials}
            </div>

            <div className="space-y-1.5 text-center sm:text-left flex-1">
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                <h2 className="text-xl font-bold text-foreground">
                  {user?.full_name || "FlowPilot Operator"}
                </h2>
                <Badge variant={user?.is_active ? "success" : "secondary"} className="self-center sm:self-auto text-xs">
                  {user?.is_active ? "Active Account" : "Inactive"}
                </Badge>
              </div>

              <div className="flex flex-wrap items-center justify-center sm:justify-start gap-4 text-xs text-muted-foreground pt-1">
                <span className="flex items-center gap-1.5">
                  <Mail className="h-3.5 w-3.5" />
                  {user?.email}
                </span>
                <span className="flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5" />
                  Member since {user?.created_at ? formatDate(user.created_at) : "N/A"}
                </span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Personal Details */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <UserIcon className="h-4 w-4 text-primary" />
              Personal Details
            </CardTitle>
            <CardDescription className="text-xs">
              Update your display name visible across agent execution logs and audit entries.
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleUpdateName}>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Email Address</label>
                <Input value={user?.email || ""} disabled className="text-xs bg-muted/50 cursor-not-allowed" />
                <span className="text-[10px] text-muted-foreground">
                  Email address cannot be changed directly.
                </span>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Full Name</label>
                <Input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="e.g. Jane Doe"
                  className="text-xs"
                />
              </div>
            </CardContent>

            <CardFooter className="border-t border-border pt-3 flex justify-end">
              <Button
                type="submit"
                size="sm"
                className="text-xs"
                disabled={updateProfileMutation.isPending || fullName === (user?.full_name || "")}
              >
                {updateProfileMutation.isPending ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    Saving...
                  </>
                ) : (
                  "Save Changes"
                )}
              </Button>
            </CardFooter>
          </form>
        </Card>

        {/* Change Password */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <Lock className="h-4 w-4 text-primary" />
              Change Password
            </CardTitle>
            <CardDescription className="text-xs">
              Update your account password with Argon2id cryptographic hashing.
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleUpdatePassword}>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">New Password</label>
                <Input
                  type="password"
                  placeholder="At least 8 characters"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  className="text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Confirm New Password</label>
                <Input
                  type="password"
                  placeholder="Repeat new password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="text-xs"
                />
              </div>
            </CardContent>

            <CardFooter className="border-t border-border pt-3 flex justify-end">
              <Button
                type="submit"
                size="sm"
                className="text-xs"
                disabled={
                  updateProfileMutation.isPending ||
                  !newPassword ||
                  newPassword.length < 8 ||
                  newPassword !== confirmPassword
                }
              >
                {updateProfileMutation.isPending ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    Updating...
                  </>
                ) : (
                  "Update Password"
                )}
              </Button>
            </CardFooter>
          </form>
        </Card>
      </div>

      {/* Security Architecture Info */}
      <Card className="border-border bg-muted/20">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-500" />
            Security & Session Architecture
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs text-muted-foreground">
          <p>
            • <strong>HttpOnly Session Storage:</strong> Authentication tokens (JWT access & refresh tokens) are isolated inside strictly scoped `HttpOnly` browser cookies. JavaScript executing in the browser cannot read or extract tokens, neutralizing cross-site scripting (XSS) token theft.
          </p>
          <p>
            • <strong>Argon2id Key Derivation:</strong> All passwords are salted and hashed using Argon2id with memory-hard parameters resistant to GPU brute-forcing.
          </p>
          <p>
            • <strong>Automated Token Renewal:</strong> The Backend-For-Frontend (BFF) proxy automatically rotates expired access tokens transparently without requiring re-login during active sessions.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
