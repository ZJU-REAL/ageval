import { useState, type ReactNode } from "react";

import { GitHubIcon } from "@/components/github-icon";
import { HoverTip } from "@ageval/shared/components/hover-tip";
import { Button } from "@ageval/shared/components/ui/button";
import {
  formatLoginError,
  redirectToGitHubLogin,
} from "@/lib/github-login";
import { cn } from "@ageval/shared/lib/utils";

/** Inline or button control that starts GitHub OAuth (no Hub intermediate page). */
export function SignInButton({
  className,
  variant = "outline",
  size = "sm",
  label = "Sign in",
}: {
  className?: string;
  variant?: "default" | "secondary" | "ghost" | "outline";
  size?: "default" | "sm" | "icon";
  label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <span className={cn("inline-flex flex-col items-start gap-0.5", className)}>
      <Button
        type="button"
        variant={variant}
        size={size}
        className="gap-1.5"
        disabled={busy}
        onClick={() => {
          void (async () => {
            setError(null);
            setBusy(true);
            try {
              await redirectToGitHubLogin();
            } catch (err) {
              setBusy(false);
              setError(formatLoginError(err));
            }
          })();
        }}
      >
        <GitHubIcon className="h-3.5 w-3.5" />
        {busy ? "Redirecting…" : label}
      </Button>
      {error ? (
        <HoverTip content={error}>
          <span className="text-[11px] text-error">{error}</span>
        </HoverTip>
      ) : null}
    </span>
  );
}

/** Text link that starts GitHub OAuth (for use inside sentences). */
export function SignInLink({
  className,
  children = "Sign in",
}: {
  className?: string;
  children?: ReactNode;
}) {
  const [busy, setBusy] = useState(false);

  return (
    <button
      type="button"
      disabled={busy}
      className={cn(
        "text-link hover:text-link-deep underline underline-offset-2 disabled:opacity-50",
        className,
      )}
      onClick={() => {
        void (async () => {
          setBusy(true);
          try {
            await redirectToGitHubLogin();
          } catch {
            setBusy(false);
            // Fall back: hard navigate to /login which auto-starts OAuth
            window.location.assign("/login");
          }
        })();
      }}
    >
      {busy ? "Redirecting…" : children}
    </button>
  );
}
