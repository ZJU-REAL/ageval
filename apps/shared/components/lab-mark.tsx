import { useState } from "react";

import { BrandMark } from "@ageval/shared/components/brand-mark";
import { BRAND_MARK_BY_ID } from "@ageval/shared/lib/brand-marks";
import { LAB_BRAND_MARK, labLogoSrc, loadModelPin } from "@ageval/shared/lib/model-pin";
import { cn } from "@ageval/shared/lib/utils";

export function LetterMark({
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
        "inline-flex shrink-0 items-center justify-center rounded-full bg-canvas-soft font-medium text-mute",
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

export function LabMark({
  lab,
  size = 20,
  className,
  title,
}: {
  lab: string;
  size?: number;
  className?: string;
  title?: string;
}) {
  const [broken, setBroken] = useState(false);
  const id = lab.trim();
  const pin = loadModelPin();
  const name = pin.labs[id]?.name || id;
  const letter = (name || id || "?").slice(0, 1).toUpperCase();
  const brandId = LAB_BRAND_MARK[id];
  if (brandId && BRAND_MARK_BY_ID.has(brandId)) {
    return (
      <BrandMark
        mark={{ kind: "catalog", id: brandId }}
        size={size}
        className={className}
        title={title || name}
      />
    );
  }

  const row = pin.labs[id];
  const src = row?.logo ? labLogoSrc(id) : "";
  const tone = row?.tone ?? "ink";

  if (!src || broken) {
    return (
      <LetterMark letter={letter} size={size} className={className} title={title || name} />
    );
  }

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full",
        tone === "ink" && "bg-white p-0.5",
        tone === "paper" && "bg-black p-0.5",
        className,
      )}
      title={title || name}
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
