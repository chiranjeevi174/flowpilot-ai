"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, CheckCircle2, Lock, ShieldAlert, Zap, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isValidating, setIsValidating] = useState(true);
  const [tokenValid, setTokenValid] = useState(false);
  const [tokenEmail, setTokenEmail] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSuccess, setIsSuccess] = useState(false);

  useEffect(() => {
    if (!token) {
      setIsValidating(false);
      setTokenValid(false);
      setTokenError("No reset token provided. Please use the link sent to your email.");
      return;
    }

    let isMounted = true;
    async function validate() {
      try {
        const res = await api.auth.validateResetToken(token);
        if (isMounted) {
          if (res.valid) {
            setTokenValid(true);
            setTokenEmail(res.email || null);
          } else {
            setTokenValid(false);
            setTokenError(res.reason || "This password reset link is invalid or has expired.");
          }
        }
      } catch {
        if (isMounted) {
          setTokenValid(false);
          setTokenError("Failed to verify token validity. Please try again.");
        }
      } finally {
        if (isMounted) {
          setIsValidating(false);
        }
      }
    }

    validate();
    return () => {
      isMounted = false;
    };
  }, [token]);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);

    const form = e.currentTarget;
    const formData = new FormData(form);
    const submittedPassword = (formData.get("password") as string) || password;
    const submittedConfirm = (formData.get("confirm_password") as string) || confirmPassword;

    if (!submittedPassword) {
      setError("Please enter your new password.");
      return;
    }

    if (submittedPassword.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }

    if (submittedPassword !== submittedConfirm) {
      setError("Passwords do not match.");
      return;
    }

    setIsLoading(true);
    try {
      await api.auth.resetPassword({
        token,
        password: submittedPassword,
      });
      setIsSuccess(true);
      toast.success("Password reset successfully! You can now log in.");
      setTimeout(() => {
        router.push("/login");
      }, 2500);
    } catch (err: any) {
      const msg = err?.data?.detail || err?.data?.error || err.message || "Failed to reset password.";
      setError(msg);
      toast.error(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-md">
      {/* Brand header */}
      <div className="flex flex-col items-center mb-8 text-center">
        <Link href="/" className="flex items-center gap-3 mb-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Zap className="h-5 w-5 fill-current text-white" />
          </div>
          <div className="flex flex-col text-left">
            <span className="font-bold text-xl tracking-tight text-foreground leading-tight">
              FlowPilot AI
            </span>
            <span className="text-[10px] text-muted-foreground font-mono tracking-wider uppercase">
              Modern Enterprise
            </span>
          </div>
        </Link>
        <p className="text-xs text-muted-foreground">Account security and password recovery</p>
      </div>

      <Card className="border-border/80 shadow-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-xl">Set New Password</CardTitle>
          <CardDescription>
            {tokenEmail ? `Choose a strong password for ${tokenEmail}` : "Choose a new secure password"}
          </CardDescription>
        </CardHeader>

        {isValidating ? (
          <CardContent className="py-12 flex flex-col items-center justify-center space-y-3">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <p className="text-xs text-muted-foreground">Verifying security token...</p>
          </CardContent>
        ) : !tokenValid ? (
          <CardContent className="space-y-4">
            <div className="flex flex-col items-center text-center p-4 rounded-xl bg-destructive/10 border border-destructive/20">
              <div className="h-12 w-12 rounded-full bg-destructive/20 flex items-center justify-center text-destructive mb-3">
                <ShieldAlert className="h-6 w-6" />
              </div>
              <h3 className="font-semibold text-sm text-destructive mb-1">Invalid or Expired Link</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {tokenError || "This password reset token has expired or has already been used."}
              </p>
            </div>

            <div className="pt-2 space-y-2">
              <Link href="/forgot-password" className="w-full block">
                <Button className="w-full h-10">Request a New Reset Link</Button>
              </Link>
              <Link href="/login" className="w-full block">
                <Button variant="ghost" className="w-full h-10 gap-2">
                  <ArrowLeft className="h-4 w-4" />
                  <span>Return to Sign In</span>
                </Button>
              </Link>
            </div>
          </CardContent>
        ) : isSuccess ? (
          <CardContent className="space-y-4">
            <div className="flex flex-col items-center text-center p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
              <div className="h-12 w-12 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 mb-3">
                <CheckCircle2 className="h-6 w-6" />
              </div>
              <h3 className="font-semibold text-sm text-emerald-300 mb-1">Password Changed Successfully</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Your password has been updated and all active sessions have been invalidated. Redirecting to login...
              </p>
            </div>

            <div className="pt-2">
              <Link href="/login" className="w-full block">
                <Button className="w-full h-10">Go to Sign In</Button>
              </Link>
            </div>
          </CardContent>
        ) : (
          <form onSubmit={handleSubmit} noValidate>
            <CardContent className="space-y-4">
              {error && (
                <div
                  id="reset-error-alert"
                  className="flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-xs text-destructive border border-destructive/20 animate-in fade-in-0"
                >
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <div className="space-y-2">
                <label htmlFor="password" className="text-xs font-semibold text-foreground">
                  New Password (min 8 chars)
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
                  <Input
                    id="password"
                    name="password"
                    type="password"
                    placeholder="••••••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-9"
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label htmlFor="confirm_password" className="text-xs font-semibold text-foreground">
                  Confirm New Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
                  <Input
                    id="confirm_password"
                    name="confirm_password"
                    type="password"
                    placeholder="••••••••••••"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="pl-9"
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                </div>
              </div>
            </CardContent>

            <CardFooter className="flex flex-col space-y-4">
              <Button
                id="reset-submit"
                type="submit"
                className="w-full h-10"
                isLoading={isLoading}
              >
                Set New Password
              </Button>
              <div className="text-center text-xs text-muted-foreground">
                <Link href="/login" className="font-semibold text-primary hover:underline">
                  Back to Sign In
                </Link>
              </div>
            </CardFooter>
          </form>
        )}
      </Card>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <Suspense
        fallback={
          <div className="flex items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        }
      >
        <ResetPasswordForm />
      </Suspense>
    </div>
  );
}
