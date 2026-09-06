import { ChevronDown, ChevronRight, Search } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type UIEvent,
} from "react";

import { FilePreview } from "@/components/file-preview";
import { FileTypeIcon } from "@/components/file-type-icon";
import { Input } from "@/components/ui/input";
import { countFiles } from "@/lib/file-icons";
import { ancestorDirPaths, type TreeNode } from "@/lib/file-tree";
import { cn } from "@/lib/utils";

/** Fixed row height for windowed tree rendering (matches h-7). */
const ROW_H = 28;
/** Extra rows above/below the viewport. */
const OVERSCAN = 16;
/**
 * Soft cap on visible rows when a dir is first opened without scrolling.
 * (Virtualization still applies; this is only for default-expand policy.)
 */
const DEFAULT_OPEN_DEPTH = 0;

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
      if (node.name.toLowerCase().includes(q) || node.path.toLowerCase().includes(q)) {
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

/** Only dirs at depth < maxDepth (root level = 0). */
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

/** Flatten open tree into ordered rows (only expanded branches). */
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

function displayPath(fullPath: string, rootPrefix?: string): string {
  const prefix = (rootPrefix || "").replace(/\/$/, "");
  if (prefix && fullPath.startsWith(prefix + "/")) {
    return fullPath.slice(prefix.length + 1);
  }
  return fullPath;
}

/**
 * Left nested tree + right code preview (Hub package files).
 *
 * Tree uses windowed rendering: only rows near the scroll viewport become DOM
 * nodes, so large packages (e.g. many tasks or shared/assets) stay responsive.
 * Directories start collapsed (depth 0) unless searching.
 */
export function FileSplitPanel({
  tree,
  treeLoading,
  selectedPath,
  onSelect,
  fileContent,
  fileLoading,
  fileNote,
  rootPrefix,
  headerEnd,
}: {
  tree: TreeNode[];
  treeLoading: boolean;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  fileContent: string | null;
  fileLoading: boolean;
  fileNote: string | null;
  rootPrefix?: string;
  /** Replaces the default "N files" label (e.g. Local | Shared switch on Task Files). */
  headerEnd?: ReactNode;
}) {
  const treeKey = useMemo(() => tree.map((n) => n.path).join("|"), [tree]);
  const [openDirs, setOpenDirs] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const lastRevealed = useRef<string | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(480);

  // Default: keep dirs collapsed so we do not mount the full package tree.
  useEffect(() => {
    lastRevealed.current = null;
    setOpenDirs(new Set(dirPathsUpToDepth(tree, DEFAULT_OPEN_DEPTH)));
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- treeKey is the intentional dep
  }, [treeKey]);

  const fileCount = useMemo(() => countFiles(tree), [tree]);
  const visibleTree = useMemo(() => filterTree(tree, query), [tree, query]);

  // Search: expand matching branch dirs so hits are reachable; still windowed.
  useEffect(() => {
    if (query.trim()) {
      setOpenDirs(new Set(allDirPaths(visibleTree)));
    } else {
      setOpenDirs(new Set(dirPathsUpToDepth(tree, DEFAULT_OPEN_DEPTH)));
    }
  }, [query, visibleTree, tree]);

  // After search/tree reset, open ancestor folders so the selected file is visible.
  useEffect(() => {
    if (!selectedPath || query.trim()) return;
    const ancestors = ancestorDirPaths(selectedPath);
    if (!ancestors.length) return;
    setOpenDirs((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const dir of ancestors) {
        if (!next.has(dir)) {
          next.add(dir);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [selectedPath, treeKey, query]);

  const flatRows = useMemo(
    () => flattenVisible(visibleTree, openDirs),
    [visibleTree, openDirs],
  );

  // Measure scroll viewport for window size.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setViewportH(el.clientHeight || 480);
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

  // After ancestor dirs open, scroll the selected file into the tree viewport.
  useEffect(() => {
    if (!selectedPath || !scrollRef.current) return;
    if (lastRevealed.current === selectedPath) return;
    const idx = flatRows.findIndex(
      (r) => r.node.type === "file" && r.node.path === selectedPath,
    );
    if (idx < 0) return;
    const el = scrollRef.current;
    const rowTop = idx * ROW_H;
    const rowBottom = rowTop + ROW_H;
    if (rowTop < el.scrollTop) {
      el.scrollTop = rowTop;
      setScrollTop(rowTop);
    } else if (rowBottom > el.scrollTop + el.clientHeight) {
      const next = rowBottom - el.clientHeight;
      el.scrollTop = next;
      setScrollTop(next);
    }
    lastRevealed.current = selectedPath;
  }, [selectedPath, flatRows, treeKey]);

  return (
    <div
      className={cn(
        "grid grid-cols-1 md:grid-cols-[280px_1fr] gap-0",
        "blob-panel overflow-hidden bg-canvas",
        "min-h-[360px] md:h-[75vh] md:min-h-[75vh] md:max-h-[75vh]",
      )}
    >
      <aside
        className={cn(
          "border-b md:border-b-0 md:border-r border-hairline bg-canvas",
          "min-h-[200px] max-h-[50vh] md:min-h-0 md:h-full md:max-h-none",
          "flex flex-col",
        )}
      >
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-hairline shrink-0">
          <span className="text-sm font-medium text-ink">
            Files
          </span>
          {headerEnd != null ? (
            headerEnd
          ) : (
            <span className="text-[11px] tabular-nums text-mute">
              {fileCount} file{fileCount === 1 ? "" : "s"}
            </span>
          )}
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
                            "text-body hover:bg-row-hover transition-colors rounded-[4px]",
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
                          <span className="truncate font-medium">{node.name}</span>
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
                          "w-full flex items-center gap-1.5 text-left h-7 pr-2 text-[12.5px] truncate transition-colors rounded-[4px]",
                          selected
                            ? "bg-canvas-soft text-ink font-medium"
                            : "text-body hover:bg-row-hover",
                        )}
                        style={{ paddingLeft: 8 + depth * 12 + 18 }}
                      >
                        <FileTypeIcon name={node.name} kind="file" />
                        <span className="truncate">{node.name}</span>
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
          "overflow-hidden bg-canvas",
        )}
      >
        {selectedPath ? (
          <div className="px-3 py-2 border-b border-hairline text-[12px] text-mute shrink-0 bg-canvas flex items-center gap-2">
            <FileTypeIcon
              name={selectedPath.split("/").pop() || selectedPath}
              kind="file"
            />
            <span className="truncate text-ink">
              {displayPath(selectedPath, rootPrefix)}
            </span>
          </div>
        ) : null}
        <div className="p-0 flex-1 min-h-0 overflow-auto bg-canvas">
          {fileLoading ? (
            <p className="text-sm text-mute p-3">Loading file…</p>
          ) : fileContent != null ? (
            <FilePreview
              path={selectedPath}
              content={fileContent}
              note={fileNote}
            />
          ) : selectedPath && fileNote ? (
            <div className="p-3 space-y-2">
              <p className="text-sm text-error font-mono break-words">{fileNote}</p>
              <p className="text-xs text-mute">
                Could not load this file for preview. Oversized package members
                should return a truncated head; other errors are shown above.
              </p>
            </div>
          ) : (
            <p className="text-sm text-mute p-3">Select a file to preview.</p>
          )}
        </div>
      </div>
    </div>
  );
}
