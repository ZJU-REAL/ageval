/** Nested file-tree helpers for package paths (Hub Files tab). */

export type TreeNode = {
  /** Segment name (e.g. harness.py or environment). */
  name: string;
  /** Full package path for files; directory path for dirs. */
  path: string;
  type: "file" | "dir";
  children?: TreeNode[];
};

/**
 * Build a nested tree from flat package paths, stripping an optional prefix
 * (e.g. ``tasks/env-postgres-min`` so the tree roots at that task).
 */
export function buildNestedTree(
  paths: Array<{ path: string; type?: string; size?: number }>,
  rootPrefix?: string,
): TreeNode[] {
  const prefix = (rootPrefix || "").replace(/\/$/, "");
  const root: TreeNode[] = [];

  const ensureDir = (nodes: TreeNode[], name: string, dirPath: string): TreeNode => {
    let node = nodes.find((n) => n.type === "dir" && n.name === name);
    if (!node) {
      node = { name, path: dirPath, type: "dir", children: [] };
      nodes.push(node);
    }
    if (!node.children) node.children = [];
    return node;
  };

  for (const item of paths) {
    if (item.type === "dir") continue;
    let rel = item.path;
    if (prefix) {
      if (rel === prefix) continue;
      if (!rel.startsWith(prefix + "/")) continue;
      rel = rel.slice(prefix.length + 1);
    }
    if (!rel) continue;
    const parts = rel.split("/").filter(Boolean);
    if (parts.length === 0) continue;

    let cursor = root;
    let acc = prefix;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      acc = acc ? `${acc}/${part}` : part;
      const isFile = i === parts.length - 1;
      if (isFile) {
        if (!cursor.some((n) => n.type === "file" && n.name === part)) {
          cursor.push({
            name: part,
            path: item.path, // keep full package path for fetch
            type: "file",
          });
        }
      } else {
        const dir = ensureDir(cursor, part, acc);
        cursor = dir.children!;
      }
    }
  }

  const sortNodes = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const n of nodes) {
      if (n.children) sortNodes(n.children);
    }
  };
  sortNodes(root);
  return root;
}

/** True when *path* is one of the prefixes or a descendant. */
export function pathMatchesPrefixes(path: string, prefixes: string[]): boolean {
  for (const raw of prefixes) {
    const prefix = raw.replace(/\/$/, "");
    if (!prefix) continue;
    if (path === prefix || path.startsWith(`${prefix}/`)) return true;
  }
  return false;
}

/** Unique ``overlays/…`` paths from a secret-free job_overlay. */
export function overlayPathsFromJobOverlay(overlay: {
  agent_profiles?: Record<string, { overlays?: string[] } | undefined>;
} | null | undefined): string[] {
  const profiles = overlay?.agent_profiles;
  if (!profiles) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of Object.values(profiles)) {
    const list = raw?.overlays;
    if (!Array.isArray(list)) continue;
    for (const item of list) {
      const path = String(item || "").trim();
      if (!path.startsWith("overlays/") || seen.has(path)) continue;
      seen.add(path);
      out.push(path);
    }
  }
  return out;
}

/** Best-effort extract of ``- overlays/…`` list items from a profiles.yaml. */
export function overlayPathsFromProfilesYaml(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*-\s+["']?(overlays\/\S+?)["']?\s*$/);
    if (!match) continue;
    const path = match[1];
    if (seen.has(path)) continue;
    seen.add(path);
    out.push(path);
  }
  return out;
}

/**
 * Overlay-source yaml paths: ``profiles.yaml`` / ``profiles*.yaml`` anywhere
 * except ``tasks/``. Matches Config Core's multi-file profiles set as Hub
 * used it before README-first loading.
 */
export function profileDocumentPaths(
  items: Array<{ path: string; type?: string }>,
): string[] {
  return items
    .filter(
      (item) =>
        item.type !== "dir" &&
        item.path.endsWith(".yaml") &&
        !item.path.startsWith("tasks/") &&
        /^profiles(\.|$)/.test(item.path.split("/").pop() || ""),
    )
    .map((item) => item.path);
}

/** Union overlay prefixes from several profiles yaml bodies, first-seen order. */
export function unionOverlayPrefixes(docs: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const doc of docs) {
    for (const path of overlayPathsFromProfilesYaml(doc)) {
      if (seen.has(path)) continue;
      seen.add(path);
      out.push(path);
    }
  }
  return out;
}

/** Parent directory paths of a file (`src/pkg/hooks.py` → `src`, `src/pkg`). */
export function ancestorDirPaths(filePath: string): string[] {
  const parts = filePath.split("/").filter(Boolean);
  if (parts.length <= 1) return [];
  const dirs: string[] = [];
  let acc = "";
  for (let i = 0; i < parts.length - 1; i++) {
    acc = acc ? `${acc}/${parts[i]}` : parts[i];
    dirs.push(acc);
  }
  return dirs;
}

/** Flatten for tests / counts. */
export function countTreeFiles(nodes: TreeNode[]): number {
  let n = 0;
  for (const node of nodes) {
    if (node.type === "file") n += 1;
    else if (node.children) n += countTreeFiles(node.children);
  }
  return n;
}
