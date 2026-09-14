import { File, Folder, FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";

import {
  loadIconUrl,
  resolveFileIconName,
  resolveFolderIconName,
} from "@ageval/shared/lib/file-icons";
import { useTheme } from "@ageval/shared/lib/theme";
import { cn } from "@ageval/shared/lib/utils";

export function FileTypeIcon({
  name,
  kind,
  expanded = false,
  className,
}: {
  /** File or folder basename (e.g. harness.py, environment). */
  name: string;
  kind: "file" | "dir";
  expanded?: boolean;
  className?: string;
}) {
  const { resolved } = useTheme();
  const light = resolved === "light";
  const [src, setSrc] = useState<string | null>(null);

  const iconName =
    kind === "dir"
      ? resolveFolderIconName(name, { expanded, light })
      : resolveFileIconName(name, { light });

  useEffect(() => {
    let cancelled = false;
    setSrc(null);
    void loadIconUrl(iconName).then((url) => {
      if (!cancelled) setSrc(url);
    });
    return () => {
      cancelled = true;
    };
  }, [iconName]);

  if (src) {
    return (
      <img
        src={src}
        alt=""
        aria-hidden
        className={cn("h-4 w-4 shrink-0 object-contain", className)}
        draggable={false}
      />
    );
  }

  // Fallback while loading / if SVG missing
  if (kind === "dir") {
    const Icon = expanded ? FolderOpen : Folder;
    return <Icon className={cn("h-4 w-4 shrink-0 text-mute", className)} />;
  }
  return <File className={cn("h-4 w-4 shrink-0 text-mute", className)} />;
}
