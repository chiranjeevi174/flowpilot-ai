"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Mail, Zap, AlertCircle, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [devResetUrl, setDevResetUrl] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);

    const form = e.currentTarget;
    const formData = new FormData(form);
    const submittedEmail = ((formData.get("email") as string) || email).trim();

    if (!submittedEmail) {
      setError("Please enter your email address.");
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(submittedEmail)) {
      setError("Please enter a valid email address.");
      return;
    }

    setIsLoading(true);
    try {
      const res = await api.auth.forgotPassword({ email: submittedEmail });
      setIsSubmitted(true);
      if (res.dev_reset_url) {
        setDevResetUrl(res.dev_reset_url);
      }
      toast.success("Instructions have been sent if an account exists.");
    } catch (err: any) {
      const msg = err?.data?.detail || err?.data?.error || err.message || "Failed to process request.";
      setError(msg);
      toast.error(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
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
            <CardTitle className="text-xl">Reset Your Password</CardTitle>
            <CardDescription>
              {isSubmitted
                ? "Check your inbox for password reset instructions"
                : "Enter your registered email address and we'll send you a recovery link"}
            </CardDescription>
          </CardHeader>

          {isSubmitted ? (
            <CardContent className="space-y-4">
              <div className="flex flex-col items-center text-center p-4 rounded-xl bg-primary/5 border border-primary/20">
                <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center text-primary mb-3">
                  <CheckCircle2 className="h-6 w-6" />
                </div>
                <h3 className="font-semibold text-sm text-foreground mb-1">Recovery Request Received</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  If an account exists with <strong className="text-foreground">{email}</strong>, you will receive an
                  email with a secure password reset link valid for 15 minutes.
                </p>
              </div>

              {devResetUrl && (
                <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs space-y-2">
                  <div className="font-semibold flex items-center gap-1.5">
                    <span>Development Mode Link:</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    Transactional email is unconfigured in this environment. You can test your recovery workflow directly:
                  </p>
                  <Link
                    href={devResetUrl}
                    className="inline-flex items-center gap-1 text-primary hover:underline font-medium text-xs break-all"
                  >
                    <span>Proceed to Reset Password</span>
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                </div>
              )}

              <div className="pt-2">
                <Link href="/login" className="w-full block">
                  <Button variant="outline" className="w-full h-10 gap-2">
                    <ArrowLeft className="h-4 w-4" />
                    <span>Return to Sign In</span>
                  </Button>
                </Link>
              </div>
            </CardContent>
          ) : (
            <form onSubmit={handleSubmit} noValidate>
              <CardContent className="space-y-4">
                {error && (
                  <div
                    id="forgot-error-alert"
                    className="flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-xs text-destructive border border-destructive/20 animate-in fade-in-0"
                  >
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}

                <div className="space-y-2">
                  <label htmlFor="email" className="text-xs font-semibold text-foreground">
                    Email Address
                  </label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
                    <Input
                      id="email"
                      name="email"
                      type="email"
                      placeholder="operator@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="pl-9"
                      required
                      autoComplete="username"
                    />
                  </div>
                </div>
              </CardContent>

              <CardFooter className="flex flex-col space-y-4">
                <Button
                  id="forgot-submit"
                  type="submit"
                  className="w-full h-10"
                  isLoading={isLoading}
                >
                  Send Recovery Link
                </Button>
                <div className="text-center text-xs text-muted-foreground">
                  Remember your password?{" "}
                  <Link href="/login" className="font-semibold text-primary hover:underline">
                    Back to Sign In
                  </Link>
                </div>
              </CardFooter>
            </form>
          )}
        </Card>
      </div>
    </div>
  );
}
