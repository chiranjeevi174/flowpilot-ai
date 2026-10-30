"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Lock, Mail, Zap, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);

    // Support browser autofill / password managers by pulling directly from form inputs if populated
    const form = e.currentTarget;
    const formData = new FormData(form);
    const submittedEmail = ((formData.get("email") as string) || email).trim();
    const submittedPassword = (formData.get("password") as string) || password;

    // Client-side validation per requirements
    if (!submittedEmail) {
      setError("Please enter your email address.");
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(submittedEmail)) {
      setError("Please enter a valid email address.");
      return;
    }

    if (!submittedPassword) {
      setError("Please enter your password.");
      return;
    }

    setIsLoading(true);
    try {
      await login(submittedEmail, submittedPassword);
      toast.success("Welcome back to FlowPilot AI!");
      router.push("/dashboard");
    } catch (err: any) {
      const errorCode = err?.data?.error_code;
      let displayError = err?.data?.detail || err?.data?.error || err.message;

      // Handle structured error codes cleanly
      if (errorCode === "USER_NOT_FOUND") {
        displayError = "No account found with this email address.";
      } else if (errorCode === "INCORRECT_PASSWORD") {
        displayError = "Incorrect password. Please try again.";
      } else if (errorCode === "RATE_LIMITED" || err?.status === 429) {
        displayError = "Too many attempts. Please try again later.";
      } else if (errorCode === "INVALID_CREDENTIALS") {
        displayError = "Invalid email or password.";
      }

      setError(displayError);
      toast.error(displayError);
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
          <p className="text-xs text-muted-foreground">Sign in to your autonomous agent workspace</p>
        </div>

        <Card className="border-border/80 shadow-md">
          <CardHeader className="space-y-1">
            <CardTitle className="text-xl">Welcome Back</CardTitle>
            <CardDescription>Enter your account credentials to access workflows</CardDescription>
          </CardHeader>

          <form onSubmit={handleSubmit} noValidate>
            <CardContent className="space-y-4">
              {error && (
                <div
                  id="login-error-alert"
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

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label htmlFor="password" className="text-xs font-semibold text-foreground">
                    Password
                  </label>
                  <Link
                    href="/forgot-password"
                    id="forgot-password-link"
                    className="text-xs text-primary hover:underline font-medium"
                  >
                    Forgot password?
                  </Link>
                </div>
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
                    autoComplete="current-password"
                  />
                </div>
              </div>
            </CardContent>

            <CardFooter className="flex flex-col space-y-4">
              <Button
                id="login-submit"
                type="submit"
                className="w-full h-10"
                isLoading={isLoading}
              >
                Sign In
              </Button>
              <div className="text-center text-xs text-muted-foreground">
                Don&apos;t have an account?{" "}
                <Link href="/register" className="font-semibold text-primary hover:underline">
                  Create an account
                </Link>
              </div>
            </CardFooter>
          </form>
        </Card>
      </div>
    </div>
  );
}
