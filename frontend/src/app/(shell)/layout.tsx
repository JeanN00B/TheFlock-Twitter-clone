"use client";

import { type ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { SquarePen } from "lucide-react";
import { useApp } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { useSession } from "@/features/auth/session-store";
import { ApiError } from "@/lib/api/port";
import { AppSidebar } from "./app-sidebar";

/**
 * Gated home shell (P1): shadcn sidebar chrome (brand nav + session
 * footer) around the authenticated outlet. Restores identity with
 * GET /auth/me on mount; an expired session clears identity and routes
 * to /login. /login and /register stay outside this group by construction
 * (they live at the app root, not under `(shell)`).
 */
export default function ShellLayout({ children }: { children: ReactNode }) {
  const { gateway } = useApp();
  const { setFromLogin, clear } = useSession();
  const router = useRouter();

  useEffect(() => {
    let live = true;
    gateway
      .me()
      .then((user) => {
        if (live) setFromLogin(user);
      })
      .catch((err) => {
        if (!live) return;
        // Expired session gates to /login. The central 401 wiring already
        // fires on this me() rejection; the explicit clear + push keeps the
        // shell's gating contract readable at the seam that owns it.
        if (err instanceof ApiError && err.status === 401) {
          clear();
          router.push("/login");
        }
      });
    return () => {
      live = false;
    };
  }, [gateway, setFromLogin, clear, router]);

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="flex items-center gap-2 border-b p-2">
          <SidebarTrigger />
          <label htmlFor="shell-search" className="sr-only">
            Search
          </label>
          <Input
            id="shell-search"
            type="search"
            autoComplete="off"
            placeholder="Search by exact username"
            className="max-w-xs"
          />
          <Button
            type="button"
            disabled
            title="Composer coming soon"
            className="ml-auto"
          >
            <SquarePen data-icon="inline-start" />
            New post
          </Button>
        </header>
        <div className="flex min-w-0 flex-1 flex-col gap-4 p-4">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}
