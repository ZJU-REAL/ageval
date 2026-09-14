/**
 * Resolve Material Icon Theme SVGs by file / folder name (Harbor-like explorer).
 * Manifest maps names → icon ids; SVGs are lazy-loaded via Vite import.meta.glob.
 */

// Slimmed local copy (fileNames + extensions only — full package JSON is ~440KB).
import manifest from "@ageval/shared/lib/material-icons-slim.json";

type IconManifest = {
  file: string;
  folder: string;
  folderExpanded: string;
  fileExtensions: Record<string, string>;
  fileNames: Record<string, string>;
  folderNames: Record<string, string>;
  folderNamesExpanded: Record<string, string>;
  light?: {
    fileExtensions?: Record<string, string>;
    fileNames?: Record<string, string>;
    folderNames?: Record<string, string>;
    folderNamesExpanded?: Record<string, string>;
  };
};

const theme = manifest as unknown as IconManifest;

/** Lazy loaders — avoids shipping every SVG in the main chunk. */
const iconLoaders = import.meta.glob(
  "/node_modules/material-icon-theme/icons/*.svg",
  { query: "?url", import: "default" },
) as Record<string, () => Promise<string>>;

const loaderByName = new Map<string, () => Promise<string>>();
for (const [path, loader] of Object.entries(iconLoaders)) {
  const base = path.split("/").pop() || "";
  const name = base.replace(/\.svg$/i, "");
  loaderByName.set(name, loader);
}

const urlCache = new Map<string, string | null>();

function pickLight(
  baseName: string,
  lightMap: Record<string, string> | undefined,
  key: string,
): string {
  if (lightMap?.[key]) return lightMap[key];
  return baseName;
}

/** Longest matching file extension key (e.g. "d.ts" before "ts"). */
function matchExtension(
  fileName: string,
  map: Record<string, string>,
): string | undefined {
  const lower = fileName.toLowerCase();
  const parts = lower.split(".");
  if (parts.length < 2) return undefined;
  for (let i = 1; i < parts.length; i++) {
    const ext = parts.slice(i).join(".");
    if (map[ext]) return map[ext];
  }
  return undefined;
}

export function resolveFileIconName(
  fileName: string,
  options: { light?: boolean } = {},
): string {
  const light = Boolean(options.light);
  const base = fileName.split("/").pop() || fileName;
  const lower = base.toLowerCase();

  const byName = theme.fileNames[lower];
  if (byName) {
    return light ? pickLight(byName, theme.light?.fileNames, lower) : byName;
  }

  const byExt = matchExtension(lower, theme.fileExtensions);
  if (byExt) {
    if (light && theme.light?.fileExtensions) {
      const parts = lower.split(".");
      for (let i = 1; i < parts.length; i++) {
        const ext = parts.slice(i).join(".");
        if (theme.light.fileExtensions[ext]) {
          return theme.light.fileExtensions[ext];
        }
      }
    }
    return byExt;
  }

  return theme.file || "file";
}

export function resolveFolderIconName(
  folderName: string,
  options: { expanded: boolean; light?: boolean },
): string {
  const light = Boolean(options.light);
  const expanded = Boolean(options.expanded);
  const base = folderName.split("/").pop() || folderName;
  const lower = base.toLowerCase();
  if (expanded) {
    const named = theme.folderNamesExpanded[lower];
    if (named) {
      return light
        ? pickLight(named, theme.light?.folderNamesExpanded, lower)
        : named;
    }
    return theme.folderExpanded || "folder-open";
  }
  const named = theme.folderNames[lower];
  if (named) {
    return light ? pickLight(named, theme.light?.folderNames, lower) : named;
  }
  return theme.folder || "folder";
}

/** Resolve icon SVG URL (cached). Returns null if missing. */
export async function loadIconUrl(iconName: string): Promise<string | null> {
  if (!iconName) return null;
  if (urlCache.has(iconName)) return urlCache.get(iconName) ?? null;
  const loader =
    loaderByName.get(iconName) ||
    loaderByName.get(iconName.replace(/_/g, "-"));
  if (!loader) {
    urlCache.set(iconName, null);
    return null;
  }
  try {
    const url = await loader();
    urlCache.set(iconName, url);
    return url;
  } catch {
    urlCache.set(iconName, null);
    return null;
  }
}

export function countFiles(nodes: { type: string; children?: unknown[] }[]): number {
  let n = 0;
  for (const node of nodes) {
    if (node.type === "file") n += 1;
    else if (Array.isArray(node.children)) {
      n += countFiles(node.children as { type: string; children?: unknown[] }[]);
    }
  }
  return n;
}
