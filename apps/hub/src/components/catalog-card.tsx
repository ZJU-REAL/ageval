import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { BrandMark } from "@/components/brand-mark";
import { BuiltinMark } from "@/components/builtin-mark";
import { MarketplaceCounts } from "@/components/marketplace-counts";
import { OfficialMark } from "@/components/official-mark";
import { markFromPackage } from "@/lib/brand-marks";
import {
  catalogPreviewKey,
  hydrateCatalogRow,
  readCatalogPreview,
  writeCatalogPreview,
} from "@/lib/catalog-cache";
import {
  getPackageByDigest,
  isBuiltinPackage,
  packageDisplayTitle,
  type PackageRelease,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { cn, formatDay } from "@/lib/utils";

type CatalogKind = "plugin" | "agent";

function hasPreview(kind: CatalogKind, row: PackageRelease): boolean {
  return kind === "plugin" ? Boolean(row.plugin_preview) : Boolean(row.agent_preview);
}

function descriptionOf(kind: CatalogKind, row: PackageRelease): string | null {
  const raw =
    kind === "plugin"
      ? row.plugin_preview?.description
      : row.agent_preview?.description;
  const text = (raw || "").replace(/\s+/g, " ").trim();
  return text || null;
}

function rowKey(row: PackageRelease): string {
  return catalogPreviewKey(row);
}

export function CatalogCard({
  kind,
  row,
  onOpen,
}: {
  kind: CatalogKind;
  row: PackageRelease;
  onOpen: (id: string) => void;
}) {
  const builtin = isBuiltinPackage(row);
  const title = packageDisplayTitle(row.dataset_id, row.display_name);
  const description = descriptionOf(kind, row);
  const previewReady = hasPreview(kind, row);
  const updated =
    !builtin && row.created_at != null ? formatDay(row.created_at) : null;

  function open() {
    onOpen(row.dataset_id);
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  }

  return (
    <article
      tabIndex={0}
      aria-label={title}
      onClick={open}
      onKeyDown={onKeyDown}
      className={cn(
        "flex h-full flex-col rounded-[14px] border border-hairline bg-canvas p-4 text-left shadow-[var(--viewer-shadow-pop)]",
        "squish hover:bg-canvas-soft",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
        "cursor-pointer",
      )}
    >
      <p className="inline-flex min-w-0 items-end gap-2 font-medium leading-none text-ink">
        <BrandMark mark={markFromPackage(row)} size={24} />
        <span className="truncate leading-none">{title}</span>
        {builtin ? <BuiltinMark /> : row.official ? <OfficialMark /> : null}
      </p>

      <p
        className={cn(
          "mt-3 h-[3.75rem] line-clamp-3 text-sm leading-5",
          description ? "text-body" : "text-mute",
        )}
        title={description ?? undefined}
      >
        {description
          ? description
          : previewReady
            ? kind === "plugin"
              ? "ageval.plugin/1 package"
              : "ageval.agent/1 package"
            : "\u00a0"}
      </p>

      {builtin ? null : (
        <div className="mt-auto flex items-end justify-between gap-2 pt-3">
          <MarketplaceCounts
            downloadCount={row.download_count}
            favoriteCount={row.favorite_count}
            compact
            className="shrink-0"
          />
          {updated ? (
            <span className="shrink-0 font-mono text-[11px] leading-none tabular-nums text-mute">
              {updated}
            </span>
          ) : (
            <span />
          )}
        </div>
      )}
    </article>
  );
}

export function CatalogCardGrid({
  kind,
  rows,
  onOpen,
}: {
  kind: CatalogKind;
  rows: PackageRelease[];
  onOpen: (id: string) => void;
}) {
  const [previews, setPreviews] = useState<Record<string, PackageRelease>>(() => {
    const initial: Record<string, PackageRelease> = {};
    for (const row of rows) {
      const hit = readCatalogPreview(rowKey(row));
      if (hit) initial[rowKey(row)] = hit;
    }
    return initial;
  });
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const missingKey = rows
    .filter((row) => !hasPreview(kind, hydrateCatalogRow(row)))
    .map(rowKey)
    .join("\n");

  useEffect(() => {
    const pending = rowsRef.current.filter(
      (row) =>
        !isBuiltinPackage(row) &&
        Boolean(row.package_digest) &&
        !hasPreview(kind, hydrateCatalogRow(row)),
    );
    if (!pending.length) return;
    let cancelled = false;
    const token = getToken();
    void Promise.all(
      pending.map(async (row) => {
        try {
          const meta = await getPackageByDigest(
            row.dataset_id,
            row.package_digest,
            token,
          );
          writeCatalogPreview(meta);
          return [rowKey(row), meta] as const;
        } catch {
          return null;
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      const next: Record<string, PackageRelease> = {};
      for (const entry of entries) {
        if (entry) next[entry[0]] = entry[1];
      }
      if (Object.keys(next).length) {
        setPreviews((prev) => ({ ...prev, ...next }));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [kind, missingKey]);

  const resolved = useMemo(
    () =>
      rows.map((row) => {
        const hydrated = hasPreview(kind, row) ? row : hydrateCatalogRow(row);
        if (hasPreview(kind, hydrated)) {
          return {
            ...hydrated,
            download_count: row.download_count,
            favorite_count: row.favorite_count,
            favorited: row.favorited,
            icon_key: row.icon_key,
            icon_github: row.icon_github,
          };
        }
        const extra = previews[rowKey(row)];
        if (!extra) return row;
        return {
          ...extra,
          download_count: row.download_count,
          favorite_count: row.favorite_count,
          favorited: row.favorited,
          icon_key: row.icon_key,
          icon_github: row.icon_github,
        };
      }),
    [kind, rows, previews],
  );

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {resolved.map((row) => (
        <CatalogCard
          key={`${row.dataset_id}@${row.version ?? "builtin"}`}
          kind={kind}
          row={row}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}


