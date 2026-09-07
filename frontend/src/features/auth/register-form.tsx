"use client";

import { cn } from "cn";
import { UserPlusIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { useApp } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/port";

const fieldLabels: Record<string, string> = {
  email: "Email",
  username: "Username",
  displayName: "Display name",
  password: "Password",
};

function formFieldName(field: string): string {
  return field === "display_name" ? "displayName" : field;
}

function fieldMessage(field: string, code: string): string {
  const label = fieldLabels[formFieldName(field)] ?? field;
  if (code === "invalid") return `${label} is invalid.`;
  if (code === "already_exists") return `${label} is already in use.`;
  return `${label}: ${code}`;
}

export function RegisterForm({ className }: { className?: string }) {
  const { gateway } = useApp();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [success, setSuccess] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setFieldErrors({});
    setSuccess(false);
    try {
      await gateway.register({
        email: email.trim(),
        username: username.trim(),
        displayName: displayName.trim(),
        password,
      });
      setSuccess(true);
      toast.success("Account created. Redirecting to log in…");
      router.push("/login");
    } catch (err) {
      if (
        err instanceof ApiError &&
        (err.status === 422 || err.status === 409) &&
        err.fields !== undefined
      ) {
        const nextFieldErrors = Object.fromEntries(
          Object.entries(err.fields).map(([field, code]) => [
            formFieldName(field),
            fieldMessage(field, code),
          ]),
        );
        setFieldErrors(nextFieldErrors);
        if (Object.keys(nextFieldErrors).length === 0) {
          const message = "Something went wrong. Please try again.";
          setError(message);
          toast.error(message);
        }
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
                <h1 className="text-2xl font-bold">Create your account</h1>
                <p className="text-balance text-muted-foreground">
                  Join the FlockTwitter community
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="register-email">Email</Label>
                <Input
                  id="register-email"
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
                <Label htmlFor="register-username">Username</Label>
                <Input
                  id="register-username"
                  name="username"
                  autoComplete="username"
                  placeholder="alice"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  aria-invalid={fieldErrors.username !== undefined}
                  required
                />
                {fieldErrors.username !== undefined ? (
                  <p role="alert" className="text-sm text-destructive">
                    {fieldErrors.username}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="register-display-name">Display name</Label>
                <Input
                  id="register-display-name"
                  name="displayName"
                  autoComplete="name"
                  placeholder="Alice"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  aria-invalid={fieldErrors.displayName !== undefined}
                  required
                />
                {fieldErrors.displayName !== undefined ? (
                  <p role="alert" className="text-sm text-destructive">
                    {fieldErrors.displayName}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="register-password">Password</Label>
                <Input
                  id="register-password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
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
              {success ? (
                <output className="text-sm text-green-700">
                  Account created. Redirecting to log in…
                </output>
              ) : null}
              <Button type="submit" disabled={pending}>
                <UserPlusIcon />
                {pending ? "Creating account…" : "Create account"}
              </Button>
            </div>
          </form>
          <div className="relative hidden bg-muted md:block">
            <div
              aria-hidden
              className="absolute inset-0 h-full w-full bg-gradient-to-br from-primary/80 via-primary/40 to-muted"
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <UserPlusIcon className="size-12 text-primary-foreground/80" />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
