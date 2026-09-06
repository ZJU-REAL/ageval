import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { LoadingState } from "@/components/empty-state";
import { CatalogHead } from "@/components/page-head";
import { BuiltinMark } from "@/components/builtin-mark";
import { CommandStrip } from "@/components/command-strip";
import { DisplayNameEditor } from "@/components/display-name-editor";
import { EntityMarkControl } from "@/components/entity-mark-control";
import { BrandMark } from "@/components/brand-mark";
import { entityHintFromPackage, markFromPackage } from "@/lib/brand-marks";
import { OfficialMark } from "@/components/official-mark";
import { FileSplitPanel } from "@/components/file-split-panel";
import { MarketplaceCounts } from "@/components/marketplace-counts";
import { PackageOwnerOps } from "@/components/package-owner-ops";
import { PackageStarButton } from "@/components/star-toggle";
import { InlineMarkdown } from "@/components/markdown";
import { Chip } from "@/components/ui/chip";
import {
  declaredSlotsFromPreview,
  PluginSlotTimeline,
} from "@/components/plugin-slot-timeline";
import {
  decodeDatasetId,
  decodeFileContent,
  getOrg,
  getBuiltinPackageFile,
  getPackageByDigest,
  getPackageFile,
  isBuiltinPackage,
  listBuiltinPackageFiles,
  isDraftRelease,
  listPackageFiles,
  listPackageVersions,
  splitPackageId,
  updatePackageDisplayName,
  type PackageRelease,
  type PluginPreview,
  RegistryHttpError,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { buildNestedTree, type TreeNode } from "@/lib/file-tree";

export function PluginDetailPage() {
  const { pluginId: rawId } = useParams();
  const pluginId = decodeDatasetId(rawId || "");
  const token = getToken();
  const navigate = useNavigate();
  const [reloadAt, setReloadAt] = useState(0);

  const [release, setRelease] = useState<PackageRelease | null>(null);
  const [preview, setPreview] = useState<PluginPreview | null>(null);
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [filePaths, setFilePaths] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [treeLoading, setTreeLoading] = useState(true);
  const [fileLoading, setFileLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [canEditName, setCanEditName] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setTreeLoading(true);
      setError(null);
      try {
        const versions = await listPackageVersions(pluginId, token);
        if (!versions.length) {
          throw new RegistryHttpError(404, "not_found", "plugin not found");
        }
        const latest = [...versions].sort(
          (a, b) => (b.created_at ?? 0) - (a.created_at ?? 0),
        )[0];
        if (cancelled) return;

        let meta: PackageRelease = latest;
        if (isBuiltinPackage(latest)) {
          setRelease(latest);
          setPreview(latest.plugin_preview || null);
          setCanEditName(false);
          const files = await listBuiltinPackageFiles(pluginId, token);
          if (cancelled) return;
          const nested = buildNestedTree(files.items);
          setTree(nested);
          setFilePaths(
            files.items.filter((e) => e.type !== "dir").map((e) => e.path),
          );
          const prefer =
            files.items.find((e) => e.path === "plugin.yaml") ||
            files.items.find((e) => e.path === "README.md") ||
            files.items.find((e) => e.type !== "dir");
          if (prefer) setSelectedPath(prefer.path);
          return;
        }
        if (latest.package_digest) {
          try {
            meta = await getPackageByDigest(
              pluginId,
              latest.package_digest,
              token,
            );
          } catch {
            /* list meta is enough for non-preview fields */
          }
        }
        if (cancelled) return;

        if (meta.package_kind && meta.package_kind !== "plugin") {
          throw new RegistryHttpError(
            404,
            "not_found",
            "not a plugin package (use Datasets for datasets)",
          );
        }

        setRelease(meta);
        setPreview(meta.plugin_preview || null);
        if (token && meta.org_id) {
          try {
            const org = await getOrg(meta.org_id, token);
            if (!cancelled) {
              setCanEditName((org.role || "").toLowerCase() === "owner");
            }
          } catch {
            if (!cancelled) setCanEditName(false);
          }
        } else if (!cancelled) {
          setCanEditName(false);
        }

        const files = await listPackageFiles(
          pluginId,
          latest.package_digest || "",
          token,
        );
        if (cancelled) return;
        const nested = buildNestedTree(files.items);
        setTree(nested);
        setFilePaths(
          files.items.filter((e) => e.type !== "dir").map((e) => e.path),
        );
        const prefer =
          files.items.find((e) => e.path === "plugin.yaml") ||
          files.items.find((e) => e.path === "README.md") ||
          files.items.find((e) => e.type !== "dir");
        if (prefer) setSelectedPath(prefer.path);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setRelease(null);
        setPreview(null);
        setTree([]);
        setFilePaths([]);
      } finally {
        if (!cancelled) {
          setLoading(false);
          setTreeLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [pluginId, token, reloadAt]);

  const packageDigest = release?.package_digest;
  const builtin = isBuiltinPackage(release);

  useEffect(() => {
    if (!selectedPath || (!builtin && !packageDigest)) {
      setFileContent(null);
      setFileNote(null);
      return;
    }
    let cancelled = false;
    setFileLoading(true);
    setFileNote(null);
    const pending = builtin
      ? getBuiltinPackageFile(pluginId, selectedPath, token)
      : getPackageFile(pluginId, packageDigest || "", selectedPath, token);
    pending
      .then((f) => {
        if (cancelled) return;
        try {
          setFileContent(decodeFileContent(f));
        } catch {
          setFileContent(null);
          setFileNote("Could not decode file content.");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFileContent(null);
        if (err instanceof RegistryHttpError) {
          setFileNote(`${err.code}: ${err.message}`);
        } else {
          setFileNote(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pluginId, packageDigest, selectedPath, token, builtin]);

  const installCmd = useMemo(() => {
    if (!release) return `ageval plugin install ${pluginId}@<version>`;
    return `ageval plugin install ${pluginId}@${release.version}`;
  }, [pluginId, release]);

  const formatBadge =
    preview?.format ||
    (release?.package_kind === "plugin" ? "ageval.plugin/1" : null);

  const packageParts = useMemo(() => splitPackageId(pluginId), [pluginId]);

  const declared = useMemo(() => declaredSlotsFromPreview(preview), [preview]);
  const previewFiles = filePaths.length ? filePaths : preview?.files || [];

  function openSlotPath(path: string) {
    setSelectedPath(path);
    const el = document.getElementById("plugin-files");
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <>
      <CatalogHead
        title="Plugin marketplace"
        crumbs={[
          { label: "Plugin marketplace", href: "/plugins" },
          { label: pluginId || "…" },
        ]}
      />

      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <DisplayNameEditor
              value={release?.display_name?.trim() || packageParts.name}
              prefix={packageParts.org ? `${packageParts.org}/` : null}
              canEdit={Boolean(token && canEditName && release && !builtin)}
              headingClassName="text-xl font-semibold tracking-tight text-ink"
              beforeTitle={
                builtin && release ? (
                  <BrandMark mark={markFromPackage(release)} size={24} />
                ) : release ? (
                  <EntityMarkControl
                    hint={entityHintFromPackage(release)}
                    packageId={pluginId}
                    token={token}
                    canEdit={Boolean(token && canEditName)}
                    onUpdated={(patch) => {
                      setRelease((prev) =>
                        prev
                          ? {
                              ...prev,
                              icon_key: patch.icon_key,
                              icon_github: patch.icon_github,
                            }
                          : prev,
                      );
                    }}
                  />
                ) : null
              }
              afterTitle={
                builtin ? (
                  <BuiltinMark />
                ) : release?.official ? (
                  <OfficialMark />
                ) : null
              }
              onSave={async (next) => {
                const updated = await updatePackageDisplayName(pluginId, next, token);
                setRelease((prev) =>
                  prev ? { ...prev, display_name: updated.display_name || next } : prev,
                );
              }}
            />
            {formatBadge ? (
              <Chip size="sm" className="font-medium">
                {formatBadge}
              </Chip>
            ) : null}
          </div>
          {release ? (
            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-mute">
              <span>@{pluginId}</span>
              {builtin ? null : (
                <>
                  <span aria-hidden>·</span>
                  <span>
                    {isDraftRelease(release) ? "draft" : `v${release.version}`}
                  </span>
                  <span aria-hidden>·</span>
                  <MarketplaceCounts
                    downloadCount={release.download_count}
                    favoriteCount={release.favorite_count}
                  />
                </>
              )}
              {release.org_id ? (
                <>
                  <span aria-hidden>·</span>
                  <span className="inline-flex items-center gap-1">
                    org{" "}
                    <Link
                      to={`/organizations/${encodeURIComponent(release.org_id)}`}
                      className="text-link hover:text-link-deep"
                    >
                      {release.org_id}
                    </Link>
                    {release.official ? <OfficialMark kind="org" /> : null}
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
        {release && !builtin ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <PackageStarButton
              packageId={pluginId}
              release={release}
              onUpdated={(next) => {
                setRelease((prev) =>
                  prev
                    ? {
                        ...prev,
                        favorited: next.favorited,
                        favorite_count: next.favorite_count,
                      }
                    : prev,
                );
              }}
            />
            <PackageOwnerOps
              packageId={pluginId}
              release={release}
              canManage={canEditName}
              token={token}
              onUpdated={(next) => setRelease(next)}
              onDeleted={() => {
                void listPackageVersions(pluginId, token).then((rows) => {
                  if (!rows.length) navigate("/plugins");
                  else setReloadAt((n) => n + 1);
                });
              }}
              onReleased={() => setReloadAt((n) => n + 1)}
            />
          </div>
        ) : null}
      </div>

      {loading && <LoadingState label="Loading plugin" />}
      {error && (
        <div className="blob-panel p-4 text-sm">
          <p className="text-error font-medium">Could not load plugin</p>
          <p className="mt-1 text-xs text-body">{error}</p>
          <p className="mt-3">
            <Link to="/plugins" className="text-link hover:text-link-deep underline underline-offset-2">
              ← Back to marketplace
            </Link>
          </p>
        </div>
      )}

      {!loading && !error && release && (
        <div className="space-y-6">
          {preview?.description ? (
            <InlineMarkdown source={preview.description} />
          ) : null}

          {builtin ? null : (
            <section className="space-y-2">
              <h2 className="text-sm font-medium text-ink">Install (CLI)</h2>
              <CommandStrip command={installCmd} />
            </section>
          )}

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-ink">Declared slots</h2>
            <PluginSlotTimeline
              declared={declared}
              files={previewFiles}
              onOpenPath={openSlotPath}
            />
          </section>

          <section id="plugin-files" className="space-y-2">
            <h2 className="text-sm font-medium text-ink">Files</h2>
            <p className="text-xs text-mute">
              Read-only preview. The browser never executes plugin code.
            </p>
            <div className="blob-panel overflow-hidden">
              <FileSplitPanel
                tree={tree}
                treeLoading={treeLoading}
                selectedPath={selectedPath}
                onSelect={setSelectedPath}
                fileContent={fileContent}
                fileLoading={fileLoading}
                fileNote={fileNote}
              />
            </div>
          </section>
        </div>
      )}
    </>
  );
}
