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

const loginFieldLabels: Record<string, string> = {
  email: "Email",
  password: "Password",
};

function loginFieldMessage(field: string, code: string): string {
  const label = loginFieldLabels[field] ?? field;
  if (code === "invalid") return `${label} is invalid.`;
  return `${label}: ${code}`;
}

export function LoginForm({ className }: { className?: string }) {
  const { gateway } = useApp();
  const { setFromLogin } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setFieldErrors({});
    try {
      // Backend answers login with 204 empty: success carries no user body,
      // the httpOnly cookie is the session. Hydrate identity with me()
      // before navigating so the shell renders signed-in on arrival.
      await gateway.login({ email: email.trim(), password });
      try {
        const user = await gateway.me();
        setFromLogin(user);
        router.push("/");
      } catch {
        // Login already succeeded: a me() failure is never a credential
        // error and never a redirect loop — stay on /login with the
        // generic error (the central 401 wiring stays untouched).
        const message = "Something went wrong. Please try again.";
        setError(message);
        toast.error(message);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        const message = "Invalid email or password.";
        setError(message);
        toast.error(message);
      } else if (
        err instanceof ApiError &&
        err.status === 422 &&
        err.fields !== undefined
      ) {
        const nextFieldErrors = Object.fromEntries(
          Object.entries(err.fields).map(([field, code]) => [
            field,
            loginFieldMessage(field, code),
          ]),
        );
        setFieldErrors(nextFieldErrors);
        if (Object.keys(nextFieldErrors).length === 0) {
          const message = "Something went wrong. Please try again.";
          setError(message);
          toast.error(message);
        }
      } else if (err instanceof ApiError && err.status === 403) {
        const message =
          "Login is currently unavailable. Please try again later.";
        setError(message);
        toast.error(message);
      } else {
        const message = "Something went wrong. Please try again.";
        setError(message);
        toast.error(message);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={cn("flex flex-col gap-6", className)}>
      <Card className="overflow-hidden p-0">
        <CardContent className="grid p-0 md:grid-cols-2">
          <form onSubmit={onSubmit} noValidate className="p-6 md:p-8">
            <div className="flex flex-col gap-6">
              <div className="flex flex-col items-center gap-2 text-center">
                <h1 className="text-2xl font-bold">Welcome back</h1>
                <p className="text-balance text-muted-foreground">
                  Log in to your FlockTwitter account
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="login-email">Email</Label>
                <Input
                  id="login-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  aria-invalid={fieldErrors.email !== undefined}
                  required
                />
                {fieldErrors.email !== undefined ? (
                  <p role="alert" className="text-sm text-destructive">
                    {fieldErrors.email}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="login-password">Password</Label>
                <Input
                  id="login-password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  aria-invalid={fieldErrors.password !== undefined}
                  required
                />
                {fieldErrors.password !== undefined ? (
                  <p role="alert" className="text-sm text-destructive">
                    {fieldErrors.password}
                  </p>
                ) : null}
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
