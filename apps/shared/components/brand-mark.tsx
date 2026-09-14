import { useState } from "react";

import { BRAND_MARK_BY_ID, catalogAssetUrl, type ResolvedMark } from "@ageval/shared/lib/brand-marks";
import { cn } from "@ageval/shared/lib/utils";

function LetterMark({
  letter,
  size,
  className,
  title,
}: {
  letter: string;
  size: number;
  className?: string;
  title?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-canvas-soft font-mono font-medium text-mute",
        className,
      )}
      title={title}
      style={{ width: size, height: size, fontSize: Math.max(10, size * 0.48) }}
      aria-hidden
    >
      {letter}
    </span>
  );
}

export function BrandMark({
  mark,
  size = 16,
  className,
  title,
}: {
  mark: ResolvedMark;
  size?: number;
  className?: string;
  title?: string;
}) {
  const [broken, setBroken] = useState(false);

  if (mark.kind === "catalog") {
    const entry = BRAND_MARK_BY_ID.get(mark.id);
    const src = entry ? catalogAssetUrl(entry.file) : undefined;
    if (!src || broken) {
      return (
        <LetterMark
          letter={(entry?.label || mark.id).slice(0, 1).toUpperCase() || "?"}
          size={size}
          className={className}
          title={title}
        />
      );
    }
    const tone = entry?.tone ?? "color";
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-full",
          tone === "ink" && "bg-white p-0.5",
          tone === "paper" && "bg-black p-0.5",
          className,
        )}
        title={title}
        style={{ width: size, height: size }}
      >
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          className="h-full w-full object-contain"
          onError={() => setBroken(true)}
        />
      </span>
    );
  }

  if (mark.kind === "github") {
    if (broken) {
      return (
        <LetterMark
          letter={mark.login.slice(0, 1).toUpperCase() || "?"}
          size={size}
          className={className}
          title={title}
        />
      );
    }
    return (
      <img
        src={mark.src}
        alt=""
        width={size}
        height={size}
        title={title}
        referrerPolicy="no-referrer"
        className={cn(
          "inline-block shrink-0 rounded-full bg-canvas-soft object-cover shadow-[var(--viewer-shadow-pop)]",
          className,
        )}
        style={{ width: size, height: size }}
        onError={() => setBroken(true)}
      />
    );
  }

  return (
    <LetterMark letter={mark.letter} size={size} className={className} title={title} />
  );
}
