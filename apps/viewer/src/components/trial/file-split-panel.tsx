import { ChevronDown, ChevronRight, Search } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type UIEvent,
} from "react";

import { FileTypeIcon } from "@/components/file-type-icon";
import { TruncateTip } from "@/components/hover-tip";
import { Markdown } from "@/components/markdown";
import { Input } from "@/components/ui/input";
import type { TreeEntry } from "@/lib/api";
import { CodeHighlight } from "@/lib/code-highlight";
import { countFiles } from "@/lib/file-icons";
import { buildNestedTree, type TreeNode } from "@/lib/file-tree";
import { isMarkdownPath } from "@/lib/markdown-frontmatter";
import { cn } from "@/lib/utils";

import { actorLabel, type ActorRow } from "./types";

/** Fixed row height for windowed tree rendering (matches h-7). */
const ROW_H = 28;
const OVERSCAN = 16;
/** Root-level dirs start collapsed (depth 0 = no auto-open). */
const DEFAULT_OPEN_DEPTH = 0;
/** Skip heavy token highlight for huge bodies. */
const HIGHLIGHT_MAX_CHARS = 120_000;
const PLAIN_PREVIEW_MAX_CHARS = 400_000;

type FlatRow = {
  key: string;
  node: TreeNode;
  depth: number;
};

function filterTree(nodes: TreeNode[], query: string): TreeNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return nodes;
  const out: TreeNode[] = [];
  for (const node of nodes) {
    if (node.type === "file") {
      if (
        node.name.toLowerCase().includes(q) ||
        node.path.toLowerCase().includes(q)
      ) {
        out.push(node);
      }
      continue;
    }
    const kids = node.children ? filterTree(node.children, q) : [];
    if (kids.length > 0 || node.name.toLowerCase().includes(q)) {
      out.push({
        ...node,
        children: kids.length > 0 ? kids : node.children,
      });
    }
  }
  return out;
}

function allDirPaths(nodes: TreeNode[], acc: string[] = []): string[] {
  for (const n of nodes) {
    if (n.type === "dir") {
      acc.push(n.path);
      if (n.children) allDirPaths(n.children, acc);
    }
  }
  return acc;
}

function dirPathsUpToDepth(
  nodes: TreeNode[],
  maxDepth: number,
  depth = 0,
  acc: string[] = [],
): string[] {
  if (depth >= maxDepth) return acc;
  for (const n of nodes) {
    if (n.type === "dir") {
      acc.push(n.path);
      if (n.children) dirPathsUpToDepth(n.children, maxDepth, depth + 1, acc);
    }
  }
  return acc;
}

function flattenVisible(
  nodes: TreeNode[],
  openDirs: Set<string>,
  depth = 0,
  out: FlatRow[] = [],
): FlatRow[] {
  for (const node of nodes) {
    out.push({
      key: `${node.type}:${node.path}`,
      node,
      depth,
    });
    if (
      node.type === "dir" &&
      openDirs.has(node.path) &&
      node.children &&
      node.children.length > 0
    ) {
      flattenVisible(node.children, openDirs, depth + 1, out);
    }
  }
  return out;
}

/**
 * Left nested file tree (Hub-style) + right code preview.
 * Windowed tree rows + collapsed-by-default dirs for large evidence archives.
 * Preserves multi-role virtual profile grouping when groupByProfile is on.
 */
export function FileSplitPanel({
  tree,
  treeLoading,
  selectedPath,
  onSelect,
  fileContent,
  fileLoading,
  fileNote,
  groupByProfile = false,
  actors = [],
  apiGroups = null,
}: {
  tree: TreeEntry[];
  treeLoading: boolean;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  fileContent: string | null;
  fileLoading: boolean;
  fileNote: string | null;
  groupByProfile?: boolean;
  actors?: ActorRow[];
  apiGroups?: Array<{
    key: string;
    profile_id?: string | null;
    label?: string;
  }> | null;
}) {
  const nestedRoots = useMemo((): TreeNode[] => {
    const files = tree.filter((e) => e.type !== "dir");
    if (files.length === 0) return [];

    // Multi-role Agent tab: virtual profile folders → nested path tree each.
    if (groupByProfile) {
      const profileKeys = new Set(
        files.map((e) => e.profile_id).filter((p): p is string => !!p),
      );
      if (profileKeys.size >= 2) {
        const actorByPid = new Map(
          actors.map((a) => [a.profile_id || "", a] as const),
        );
        const order: string[] = [];
        if (apiGroups && apiGroups.length > 0) {
          for (const g of apiGroups) {
            if (g.key && !order.includes(g.key)) order.push(g.key);
          }
        }
        for (const e of files) {
          const key = e.profile_id || "__ungrouped__";
          if (!order.includes(key)) order.push(key);
        }

        const roots: TreeNode[] = [];
        for (const key of order) {
          const groupFiles = files.filter(
            (e) => (e.profile_id || "__ungrouped__") === key,
          );
          const nested = buildNestedTree(
            groupFiles.map((e) => ({
              path: e.path,
              type: "file",
              size: e.size ?? 0,
            })),
          );
          const label =
            key === "__ungrouped__"
              ? "other"
              : (() => {
                  const actor = actorByPid.get(key);
                  return actor ? actorLabel(actor, key) : key;
                })();
          roots.push({
            name: label,
            path: `__profile__/${key}`,
            type: "dir",
            children: nested,
          });
        }
        return roots;
      }
    }

    return buildNestedTree(
      files.map((e) => ({ path: e.path, type: "file", size: e.size ?? 0 })),
    );
  }, [tree, groupByProfile, actors, apiGroups]);

  const treeKey = useMemo(
    () => nestedRoots.map((n) => n.path).join("|") + `:${nestedRoots.length}`,
    [nestedRoots],
  );
  const [openDirs, setOpenDirs] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(420);

  useEffect(() => {
    setOpenDirs(new Set(dirPathsUpToDepth(nestedRoots, DEFAULT_OPEN_DEPTH)));
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- treeKey is the intentional dep
  }, [treeKey]);

  const fileCount = useMemo(() => countFiles(nestedRoots), [nestedRoots]);
  const visibleTree = useMemo(
    () => filterTree(nestedRoots, query),
    [nestedRoots, query],
  );

  useEffect(() => {
    if (query.trim()) {
      setOpenDirs(new Set(allDirPaths(visibleTree)));
    } else {
      setOpenDirs(new Set(dirPathsUpToDepth(nestedRoots, DEFAULT_OPEN_DEPTH)));
    }
  }, [query, visibleTree, nestedRoots]);

  const flatRows = useMemo(
    () => flattenVisible(visibleTree, openDirs),
    [visibleTree, openDirs],
  );

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setViewportH(el.clientHeight || 420);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [treeLoading, flatRows.length]);

  const onScroll = useCallback((e: UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  const totalH = flatRows.length * ROW_H;
  const visibleCount = Math.ceil(viewportH / ROW_H) + OVERSCAN * 2;
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const endIdx = Math.min(flatRows.length, startIdx + visibleCount);
  const slice = flatRows.slice(startIdx, endIdx);
  const padTop = startIdx * ROW_H;
  const padBottom = Math.max(0, totalH - padTop - slice.length * ROW_H);

  function toggleDir(path: string) {
    setOpenDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  const selectedName = selectedPath
    ? selectedPath.split("/").pop() || selectedPath
    : null;

  const previewTooLarge =
    fileContent != null && fileContent.length > HIGHLIGHT_MAX_CHARS;
  const previewDisplay =
    fileContent == null
      ? null
      : fileContent.length > PLAIN_PREVIEW_MAX_CHARS
        ? fileContent.slice(0, PLAIN_PREVIEW_MAX_CHARS) +
          `\n\n… truncated for preview (${fileContent.length.toLocaleString()} chars total)`
        : fileContent;

  return (
    <div
      className={cn(
        "grid grid-cols-1 md:grid-cols-[280px_1fr] gap-0",
        "blob-panel overflow-hidden",
        "min-h-[360px] md:h-[70vh] md:min-h-[70vh] md:max-h-[70vh]",
      )}
    >
      <aside
        className={cn(
          "border-b md:border-b-0 md:border-r border-hairline bg-canvas",
          "min-h-[160px] max-h-[50vh] md:min-h-0 md:h-full md:max-h-none",
          "flex flex-col",
        )}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b border-hairline shrink-0">
          <span className="text-sm font-medium text-ink">
            Files
          </span>
          <span className="text-[11px] tabular-nums text-mute">
            {fileCount} file{fileCount === 1 ? "" : "s"}
          </span>
        </div>
        <div className="px-2 py-2 border-b border-hairline shrink-0">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-mute" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="h-8 pl-7 text-xs bg-canvas focus-visible:border-hairline"
              aria-label="Search files"
            />
          </div>
        </div>
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-1 pt-1"
          onScroll={onScroll}
        >
          {treeLoading ? (
            <p className="text-xs text-mute p-3">Loading tree…</p>
          ) : flatRows.length === 0 ? (
            <p className="text-xs text-mute p-3">
              {query.trim() ? "No matches." : "No files in this scope."}
            </p>
          ) : (
            <div style={{ height: totalH, position: "relative" }}>
              <div style={{ height: padTop }} aria-hidden />
              <ul className="m-0 p-0 list-none">
                {slice.map((row) => {
                  const { node, depth } = row;
                  if (node.type === "dir") {
                    const open = openDirs.has(node.path);
                    return (
                      <li key={row.key} style={{ height: ROW_H }}>
                        <button
                          type="button"
                          onClick={() => toggleDir(node.path)}
                          className={cn(
                            "w-full flex items-center gap-1 text-left h-7 pr-2 text-[12.5px]",
                            "text-body hover:bg-liquid-hover transition-colors rounded-[8px]",
                          )}
                          style={{ paddingLeft: 8 + depth * 12 }}
                        >
                          {open ? (
                            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-mute" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-mute" />
                          )}
                          <FileTypeIcon
                            name={node.name}
                            kind="dir"
                            expanded={open}
                          />
                          <TruncateTip
                            text={node.name}
                            className="font-medium"
                          />
                          {node.children && node.children.length > 0 ? (
                            <span className="ml-auto pl-1 text-[10px] tabular-nums text-mute shrink-0">
                              {node.children.length}
                            </span>
                          ) : null}
                        </button>
                      </li>
                    );
                  }
                  const selected = selectedPath === node.path;
                  return (
                    <li key={row.key} style={{ height: ROW_H }}>
                      <button
                        type="button"
                        onClick={() => onSelect(node.path)}
                        className={cn(
                          "w-full flex items-center gap-1.5 text-left h-7 pr-2 text-[12.5px] transition-colors rounded-[8px]",
                          selected
                            ? "bg-canvas-soft-2 text-ink font-medium"
                            : "text-body hover:bg-liquid-hover hover:text-ink",
                        )}
                        style={{ paddingLeft: 8 + depth * 12 + 18 }}
                      >
                        <FileTypeIcon name={node.name} kind="file" />
                        <TruncateTip text={node.name} />
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div style={{ height: padBottom }} aria-hidden />
            </div>
          )}
        </div>
      </aside>
      <div
        className={cn(
          "flex flex-col min-h-[200px] md:min-h-0 md:h-full",
          "overflow-hidden",
        )}
      >
        {selectedPath ? (
          <div className="px-3 py-2 border-b border-hairline text-[12px] text-mute shrink-0 bg-canvas flex items-center gap-2">
            <FileTypeIcon name={selectedName || selectedPath} kind="file" />
            <TruncateTip text={selectedPath} className="text-ink" />
          </div>
        ) : null}
        <div className="p-0 flex-1 min-h-0 overflow-auto">
          {fileLoading ? (
            <p className="text-sm text-mute p-3">Loading file…</p>
          ) : (
            <>
              {fileNote ? (
                <p className="text-xs text-mute px-3 pt-2">{fileNote}</p>
              ) : null}
              {previewTooLarge && fileContent != null ? (
                <p className="text-xs text-mute px-3 pt-2">
                  Large file ({fileContent.length.toLocaleString()} chars) —
                  plain preview without highlighting
                  {fileContent.length > PLAIN_PREVIEW_MAX_CHARS
                    ? `, first ${PLAIN_PREVIEW_MAX_CHARS.toLocaleString()} chars`
                    : ""}
                  .
                </p>
              ) : null}
              {previewDisplay != null && isMarkdownPath(selectedPath) ? (
                <div className="p-4">
                  <Markdown
                    source={previewDisplay}
                    className="border-0 rounded-none p-0"
                  />
                </div>
              ) : previewDisplay != null ? (
                <pre
                  className={cn(
                    "m-0 p-3 min-h-full overflow-auto",
                    "whitespace-pre-wrap break-words font-mono text-[12px] leading-5",
                    "bg-code-bg text-shell-plain",
                  )}
                >
                  <code className="font-mono">
                    {previewTooLarge ? (
                      <span className="text-shell-plain">{previewDisplay}</span>
                    ) : (
                      <CodeHighlight
                        path={selectedPath}
                        content={previewDisplay}
                      />
                    )}
                  </code>
                </pre>
              ) : (
                <p className="text-sm text-mute p-3">Select a file to preview.</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
