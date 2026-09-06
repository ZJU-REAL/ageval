import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { LoadingState } from "@/components/empty-state";
import { CatalogHead } from "@/components/page-head";
import { CommandStrip } from "@/components/command-strip";
import {
  SuiteInspector,
  suiteDetailPath,
  type SuiteInspectorTab,
} from "@/components/suite-inspector";
import { toast } from "@/components/ui/toast";
import { toastError } from "@/lib/toast-error";
import {
  decodeDatasetId,
  detachPerformance,
  encodeDatasetId,
  getOrg,
  getSuite,
  isBuiltinPackage,
  latestPackageByDataset,
  listPackages,
  listPackageVersions,
  listPackageVersionsWithPerformances,
  pickPackageVersion,
  type PackageRelease,
  type SuiteRow,
  RegistryHttpError,
} from "@/lib/api";
import { getGithubUser, getToken } from "@/lib/auth";

function parseSuiteTab(
  raw: string | null,
  canManage: boolean,
): SuiteInspectorTab {
  if (raw === "plugin" || raw === "jobs") return raw;
  if (raw === "share" && canManage) return "share";
  return "profiles";
}

/**
 * Suite run detail (Profiles / Plugin / Jobs / Share). Same content as the
 * former Leaderboard inspector, as a routed page like Attempt evidence.
 */
export function SuiteDetailPage() {
  const { datasetId: rawId, suiteRunId: rawSuite } = useParams();
  const datasetId = decodeDatasetId(rawId || "");
  const suiteRunId = decodeURIComponent(rawSuite || "");
  const token = getToken();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const agentParam = (search.get("agent") || "").trim();
  const roleParam = (search.get("role") || "").trim();

  const [suite, setSuite] = useState<SuiteRow | null>(null);
  const [pluginCatalog, setPluginCatalog] = useState<PackageRelease[]>([]);
  const [overlayDigest, setOverlayDigest] = useState("");
  const [orgId, setOrgId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [canDetach, setCanDetach] = useState(false);

  useEffect(() => {
    if (!suiteRunId) {
      setSuite(null);
      setError("missing suite run id");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      getSuite(suiteRunId, token),
      datasetId
        ? listPackageVersions(datasetId, token).catch(() => [] as PackageRelease[])
        : Promise.resolve([] as PackageRelease[]),
      listPackages(token, { packageKind: "plugin" }).catch(
        () => [] as PackageRelease[],
      ),
    ])
      .then(([row, versions, plugins]) => {
        if (cancelled) return;
        setSuite(row);
        setPluginCatalog(latestPackageByDataset(plugins));
        const bound =
          versions.find((item) => item.version === row.dataset_version) ||
          pickPackageVersion(versions);
        setOverlayDigest(bound?.package_digest || "");
        setOrgId(bound?.org_id || null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setSuite(null);
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, suiteRunId, token]);

  useEffect(() => {
    if (!agentParam || !roleParam || !token) {
      setCanDetach(false);
      return;
    }
    let cancelled = false;
    listPackageVersionsWithPerformances(agentParam, token, {
      packageKind: "agent",
    })
      .then(async (listed) => {
        if (cancelled) return;
        const latest = [...listed.items].sort(
          (a, b) => (b.created_at ?? 0) - (a.created_at ?? 0),
        )[0];
        if (!latest) {
          setCanDetach(false);
          return;
        }
        if (isBuiltinPackage(latest)) {
          setCanDetach(Boolean(listed.performanceCollect?.can_edit));
          return;
        }
        if (!latest.org_id) {
          setCanDetach(false);
          return;
        }
        try {
          const org = await getOrg(latest.org_id, token);
          if (!cancelled) {
            setCanDetach((org.role || "").toLowerCase() === "owner");
          }
        } catch {
          if (!cancelled) setCanDetach(false);
        }
      })
      .catch(() => {
        if (!cancelled) setCanDetach(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentParam, roleParam, token]);

  const selfLogin = (getGithubUser() || "").toLowerCase();
  const canManage =
    Boolean(selfLogin) &&
    (suite?.uploaded_by || "").toLowerCase() === selfLogin;
  const tab = parseSuiteTab(search.get("tab"), canManage);
  const leaderboardHref = datasetId
    ? `/datasets/${encodeDatasetId(datasetId)}?tab=leaderboard`
    : "/datasets";

  function setTab(next: SuiteInspectorTab) {
    const n = new URLSearchParams(search);
    if (next === "profiles") n.delete("tab");
    else n.set("tab", next);
    setSearch(n, { replace: true });
  }

  async function removePerformance() {
    if (!agentParam || !roleParam || !token) return;
    try {
      await detachPerformance(
        agentParam,
        { suite_run_id: suiteRunId, role: roleParam },
        token,
      );
      toast("Removed from Performance");
      navigate(`/agents/${encodeDatasetId(agentParam)}`);
    } catch (err) {
      toastError(err);
    }
  }

  if (
    suite?.dataset_id &&
    datasetId &&
    suite.dataset_id !== datasetId
  ) {
    return (
      <Navigate
        to={suiteDetailPath(suite.dataset_id, suite.suite_run_id, {
          tab: search.get("tab"),
          agent: agentParam,
          role: roleParam,
        })}
        replace
      />
    );
  }

  return (
    <>
      <CatalogHead
        title="Datasets"
        crumbs={[
          { label: "Datasets", href: "/datasets" },
          {
            label: datasetId || "…",
            href: leaderboardHref,
          },
          { label: suiteRunId || "…" },
        ]}
      />
      {loading ? <LoadingState label="Loading suite run" /> : null}
      {error ? (
        <div className="blob-panel space-y-3 p-6">
          <p className="font-mono text-sm text-error">{error}</p>
          <p className="text-sm text-mute">
            This suite may be private, deleted, or not uploaded. Return to{" "}
            <Link
              to={leaderboardHref}
              className="text-link hover:text-link-deep underline-offset-2 hover:underline"
            >
              Leaderboard
            </Link>
            .
          </p>
          <CommandStrip
            command={`ageval results upload-suite <dataset-root> --suite-run ${suiteRunId || "<id>"} --with-attempts`}
          />
        </div>
      ) : null}
      {!loading && !error && suite ? (
        <SuiteInspector
          suite={suite}
          datasetId={datasetId || suite.dataset_id || ""}
          overlayDigest={overlayDigest}
          pluginCatalog={pluginCatalog}
          orgId={orgId}
          canManage={canManage}
          tab={tab}
          onTabChange={setTab}
          onSuiteUpdated={(_id, patch) =>
            setSuite((prev) => (prev ? { ...prev, ...patch } : prev))
          }
          onSuiteDeleted={() => navigate(leaderboardHref)}
          canDetachPerformance={canDetach}
          onRemovePerformance={() => void removePerformance()}
        />
      ) : null}
    </>
  );
}
