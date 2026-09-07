"use client";

import { useRouter } from "next/navigation";
import { ThemeProvider } from "next-themes";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";
import { Toaster } from "@/components/ui/sonner";
import { SessionProvider, useSession } from "@/features/auth/session-store";
import { type App, createApp } from "@/lib/composition";

const AppContext = createContext<App | null>(null);

export function useApp(): App {
  const app = useContext(AppContext);
  if (app === null) throw new Error("useApp must be used within AppProviders");
  return app;
}

/** Central 401 wiring: any session end clears state and routes to /login. */
function SessionEndBinding({ app }: { app: App }) {
  const { clear } = useSession();
  const router = useRouter();
  useEffect(() => {
    app.onSessionEnd(() => {
      clear();
      router.push("/login");
    });
  }, [app, clear, router]);
  return null;
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [app] = useState(() =>
    createApp(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"),
  );
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <AppContext.Provider value={app}>
        <SessionProvider>
          <SessionEndBinding app={app} />
          {children}
          <Toaster />
        </SessionProvider>
      </AppContext.Provider>
    </ThemeProvider>
  );
}
