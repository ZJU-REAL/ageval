import { createContext, useContext } from "react";

import type { ViewSession } from "@/lib/api";

export type SessionState = {
  session: ViewSession | null;
  error: string | null;
};

export const SessionContext = createContext<SessionState | null>(null);

export function useSession(): SessionState {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("SessionProvider missing");
  }
  return value;
}

export function useReadySession(): ViewSession {
  const { session } = useSession();
  if (!session) {
    throw new Error("session unavailable");
  }
  return session;
}
