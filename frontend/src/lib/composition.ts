import { createBackendGateway } from "./api/fetch-client";
import type { BackendGateway } from "./api/port";

export interface App {
  gateway: BackendGateway;
  /** Register the session-end handler (clear + route to /login). */
  onSessionEnd: (handler: () => void) => void;
}

/**
 * Single construction site for the frontend object graph.
 * Factory-called-once from `app/providers.tsx`, context-distributed,
 * no globals. Pages/hooks never import `fetch-client` directly.
 */
export function createApp(baseUrl: string): App {
  let sessionEndHandler: (() => void) | null = null;
  const gateway = createBackendGateway(baseUrl, {
    onSessionEnd: () => sessionEndHandler?.(),
  });
  return {
    gateway,
    onSessionEnd(handler: () => void) {
      sessionEndHandler = handler;
    },
  };
}
