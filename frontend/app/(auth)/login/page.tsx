"use client";

import { useState } from "react";
import Image from "next/image";
import { EyeIcon, EyeOffIcon, Loader2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"signin" | "register">("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await register(username, password);
      } else {
        await login(username, password);
      }
      // AuthProvider redirects to "/".
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't reach the server",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Image
            src="/logo.svg"
            alt="Sectors Agent logo"
            width={32}
            height={32}
            className="drop-shadow-[0_2px_5px_rgb(62_198_173/0.45)]"
          />
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">
            Sectors Agent
          </h1>
          <p className="text-sm text-muted-foreground">
            IDX market analysis. Information, not advice.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base">
              {mode === "signin" ? "Sign in" : "Create account"}
            </CardTitle>
            <CardDescription>
              {mode === "signin"
                ? "Enter your credentials."
                : "Pick a username and password (8+ characters)."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label
                  htmlFor="username"
                  className="text-xs text-muted-foreground"
                >
                  Username
                </Label>
                <Input
                  id="username"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label
                  htmlFor="password"
                  className="text-xs text-muted-foreground"
                >
                  Password
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete={
                      mode === "register" ? "new-password" : "current-password"
                    }
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pr-9"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 cursor-pointer text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {showPassword ? (
                      <EyeOffIcon className="size-4" />
                    ) : (
                      <EyeIcon className="size-4" />
                    )}
                  </button>
                </div>
              </div>
              {error && (
                <p className="font-mono text-xs text-destructive">{error}</p>
              )}
              <Button type="submit" disabled={busy} className="mt-1 w-full">
                {busy ? (
                  <>
                    <Loader2Icon className="size-4 animate-spin" />
                    {mode === "register" ? "Creating account…" : "Signing in…"}
                  </>
                ) : mode === "register" ? (
                  "Create account"
                ) : (
                  "Sign in"
                )}
              </Button>
              <button
                type="button"
                onClick={() => {
                  setMode(mode === "signin" ? "register" : "signin");
                  setError(null);
                }}
                className="cursor-pointer text-center font-mono text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                {mode === "signin"
                  ? "No account? Create one"
                  : "Have an account? Sign in"}
              </button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
