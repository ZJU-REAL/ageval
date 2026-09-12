import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { SignInLink } from "@/components/sign-in-button";
import { completeWebLogin, RegistryHttpError } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { formatLoginError } from "@/lib/github-login";
import { takeReturnPath } from "@/lib/return-path";

/** OAuth redirect target: ?code=&state= → Registry token → /leaderboard */
export function LoginCallbackPage() {
  const [params] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  // React StrictMode remounts effects in dev; exchange GitHub code exactly once.
  const startedRef = useRef(false);

  const code = params.get("code");
  const oauthState = params.get("state");
  const oauthError = params.get("error");
  const desc = params.get("error_description");

  useEffect(() => {
    if (oauthError) {
      setError(desc || oauthError || "GitHub denied authorization");
      return;
    }
    if (!code || !oauthState) {
      setError("Missing authorization. Sign in again.");
      return;
    }
    if (startedRef.current) return;
    startedRef.current = true;

    const redirectUri = `${window.location.origin}/login/callback`;
    completeWebLogin({ code, state: oauthState, redirectUri })
      .then((session) => {
        setToken(
          session.token,
          session.github_user,
          session.github_name,
          session.avatar_url,
        );
        window.location.replace(takeReturnPath("/leaderboard"));
      })
      .catch((err: unknown) => {
        if (err instanceof RegistryHttpError && err.code === "invalid_state") {
          setError("Session expired. Sign in again.");
          return;
        }
        setError(formatLoginError(err));
      });
  }, [code, oauthState, oauthError, desc]);

  return (
    <>
      <div className="max-w-md">
        <h1 className="text-xl font-semibold tracking-tight text-ink mb-2">
          {error ? "Sign-in failed" : "Completing sign-in…"}
        </h1>
        {error ? (
          <>
            <p className="text-sm text-error mb-4">{error}</p>
            <SignInLink className="text-sm text-link hover:text-link-deep">
              Try again
            </SignInLink>
          </>
        ) : (
          <p className="text-sm text-mute">Finishing with GitHub…</p>
        )}
      </div>
    </>
  );
}
