import { useEffect, useState, type ReactNode } from "react";

import { fetchSession } from "@/lib/api";
import { SessionContext } from "@/lib/session";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Awaited<ReturnType<typeof fetchSession>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSession()
      .then((data) => {
        if (!cancelled) setSession(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <SessionContext.Provider value={{ session, error }}>{children}</SessionContext.Provider>;
}
