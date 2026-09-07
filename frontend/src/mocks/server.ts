import { setupServer } from "msw/node";
import { handlers } from "./handlers";

/** Node-side MSW server for tests only (no dev worker, no live HTTP). */
export const server = setupServer(...handlers);
