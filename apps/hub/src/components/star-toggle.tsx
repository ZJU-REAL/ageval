import { useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { Star } from "lucide-react";

import { setPackageFavorite, type PackageRelease } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { rememberReturnPath } from "@/lib/return-path";
import { cn } from "@ageval/shared/lib/utils";

function starBurst() {
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return [];
  }
  const stamp = Date.now();
  return Array.from({ length: 8 }, (_, i) => {
    const angle = (Math.PI * 2 * i) / 8;
    return {
      id: stamp + i,
      tx: Math.cos(angle) * 18,
      ty: Math.sin(angle) * 18,
    };
  });
}

export function StarToggle({
  starred,
  busy = false,
  onToggle,
}: {
  starred: boolean;
  busy?: boolean;
  onToggle: () => void;
}) {
  const [pop, setPop] = useState(false);
  const [bits, setBits] = useState<Array<{ id: number; tx: number; ty: number }>>(
    [],
  );

  function celebrate() {
    const nextBits = starBurst();
    if (nextBits.length === 0) return;
    setPop(true);
    setBits(nextBits);
    window.setTimeout(() => setPop(false), 220);
    window.setTimeout(() => setBits([]), 400);
  }

  return (
    <button
      type="button"
      disabled={busy}
      aria-pressed={starred}
      aria-label={starred ? "Unstar" : "Star"}
      title={starred ? "Unstar" : "Star"}
      onClick={() => {
        if (!starred) celebrate();
        onToggle();
      }}
      className={cn(
        "relative inline-flex h-8 w-8 items-center justify-center overflow-visible rounded-[8px] squish hover:bg-liquid-hover",
        "transition-colors duration-200 ease-smooth",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
        "disabled:pointer-events-none disabled:opacity-50",
        starred ? "text-star" : "text-mute hover:text-body",
      )}
    >
      <Star
        className={cn(
          "h-4 w-4 motion-safe:transition-transform motion-safe:duration-[240ms] motion-safe:ease-spring",
          pop && "scale-[1.22]",
        )}
        strokeWidth={1.75}
        fill={starred || pop ? "currentColor" : "none"}
        aria-hidden
      />
      {bits.map((bit) => (
        <span
          key={bit.id}
          data-ageval-burst=""
          className="pointer-events-none absolute left-1/2 top-1/2 h-1 w-1 rounded-full bg-star"
          style={
            {
              "--tx": `${bit.tx}px`,
              "--ty": `${bit.ty}px`,
            } as CSSProperties
          }
        />
      ))}
    </button>
  );
}

export function PackageStarButton({
  packageId,
  release,
  onUpdated,
}: {
  packageId: string;
  release: PackageRelease;
  onUpdated: (next: { favorited: boolean; favorite_count: number }) => void;
}) {
  const navigate = useNavigate();
  const token = getToken();
  const [busy, setBusy] = useState(false);
  return (
    <StarToggle
      starred={Boolean(release.favorited)}
      busy={busy}
      onToggle={() => {
        if (!token) {
          rememberReturnPath(window.location.pathname + window.location.search);
          navigate("/login");
          return;
        }
        setBusy(true);
        const next = !release.favorited;
        void setPackageFavorite(packageId, next, token)
          .then(onUpdated)
          .finally(() => setBusy(false));
      }}
    />
  );
}
