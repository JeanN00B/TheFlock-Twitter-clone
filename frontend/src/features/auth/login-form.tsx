"use client";

import { cn } from "cn";
import { LogInIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { useApp } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSession } from "@/features/auth/session-store";
import { ApiError } from "@/lib/api/port";

export function LoginForm({ className }: { className?: string }) {
  const { gateway } = useApp();
  const { setFromLogin } = useSession();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const user = await gateway.login({ username: username.trim(), password });
      setFromLogin(user);
      router.push("/");
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 401
          ? "Invalid username or password."
          : "Something went wrong. Please try again.";
      setError(message);
      toast.error(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={cn("flex flex-col gap-6", className)}>
      <Card className="overflow-hidden p-0">
        <CardContent className="grid p-0 md:grid-cols-2">
          <form onSubmit={onSubmit} className="p-6 md:p-8">
            <div className="flex flex-col gap-6">
              <div className="flex flex-col items-center gap-2 text-center">
                <h1 className="text-2xl font-bold">Welcome back</h1>
                <p className="text-balance text-muted-foreground">
                  Log in to your FlockTwitter account
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="login-username">Username</Label>
                <Input
                  id="login-username"
                  autoComplete="username"
                  placeholder="alice"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="login-password">Password</Label>
                <Input
                  id="login-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </div>
              {error !== null ? (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              ) : null}
              <Button type="submit" disabled={pending}>
                <LogInIcon />
                {pending ? "Logging in…" : "Log in"}
              </Button>
              <p className="text-center text-sm text-muted-foreground">
                Don&apos;t have an account?{" "}
                <Link
                  href="/register"
                  className="font-medium text-foreground underline underline-offset-4"
                >
                  Create an account
                </Link>
              </p>
            </div>
          </form>
          <div className="relative hidden bg-muted md:block">
            <div
              aria-hidden
              className="absolute inset-0 h-full w-full bg-gradient-to-br from-primary/80 via-primary/40 to-muted"
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <LogInIcon className="size-12 text-primary-foreground/80" />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
