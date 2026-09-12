import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CatalogCardGrid } from "@/components/catalog-card";
import { LoadingState } from "@/components/empty-state";
import { DescriptionEditor } from "@/components/description-editor";
import { GitHubIcon } from "@/components/github-icon";
import { PageHead } from "@/components/page-head";
import { MaintainerMark } from "@/components/maintainer-mark";
import { OfficialMark } from "@/components/official-mark";
import { INTERNAL_LINK_CLASS } from "@/lib/links";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  encodeDatasetId,
  getUser,
  latestPackageByDataset,
  listPackages,
  packageDisplayTitle,
  updateUserDescription,
  versionLabel,
  type PackageRelease,
  type UserPublic,
  RegistryHttpError,
} from "@/lib/api";
import { getGithubUser, getToken } from "@/lib/auth";

const USER_DESCRIPTION_MAX = 280;

export function UserPage() {
  const { login: rawLogin } = useParams();
  const login = rawLogin ? decodeURIComponent(rawLogin) : "";
  const navigate = useNavigate();
  const token = getToken();
  const selfLogin = (getGithubUser() || "").toLowerCase();

  const [user, setUser] = useState<UserPublic | null>(null);
  const [datasets, setDatasets] = useState<PackageRelease[]>([]);
  const [plugins, setPlugins] = useState<PackageRelease[]>([]);
  const [agents, setAgents] = useState<PackageRelease[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!login) {
      setLoading(false);
      setError("not_found: user not found");
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const profile = await getUser(login);
        if (cancelled) return;
        setUser(profile);
        setError(null);
        const uid = profile.user_id;
        const [datasetRows, pluginRows, agentRows] = await Promise.all([
          listPackages(token, { packageKind: "dataset" }).catch(
            () => [] as PackageRelease[],
          ),
          listPackages(token, { packageKind: "plugin" }).catch(
            () => [] as PackageRelease[],
          ),
          listPackages(token, { packageKind: "agent" }).catch(
            () => [] as PackageRelease[],
          ),
        ]);
        if (cancelled) return;
        const mine = (rows: PackageRelease[]) =>
          latestPackageByDataset(rows).filter(
            (row) =>
              row.visibility === "public" &&
              (row.uploaded_by || "").toLowerCase() === uid,
          );
        setDatasets(mine(datasetRows));
        setPlugins(mine(pluginRows));
        setAgents(mine(agentRows));
      } catch (err: unknown) {
        if (cancelled) return;
        setUser(null);
        setDatasets([]);
        setPlugins([]);
        setAgents([]);
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [login, token]);

  const title = useMemo(
    () => user?.display_name || user?.user_id || login,
    [user, login],
  );
  const isSelf = Boolean(token && user && user.user_id === selfLogin);
  const githubHref = user
    ? `https://github.com/${encodeURIComponent(user.user_id)}`
    : "";
  const avatar =
    user?.avatar_url ||
    (user?.user_id
      ? `https://github.com/${encodeURIComponent(user.user_id)}.png?size=64`
      : "");

  return (
    <>
      <PageHead title={title || "…"} />

      {loading ? (
        <LoadingState label="Loading user" />
      ) : error ? (
        <div className="blob-panel p-4 text-sm">
          <p className="text-error font-medium">Could not load user</p>
          <p className="mt-1 text-xs text-body">{error}</p>
        </div>
      ) : user ? (
        <div className="space-y-8">
          <div className="flex items-center gap-3 min-w-0">
            {avatar ? (
              <img
                src={avatar}
                alt=""
                width={48}
                height={48}
                className="h-12 w-12 rounded-full bg-canvas-soft object-cover shrink-0 shadow-[var(--viewer-shadow-pop)]"
              />
            ) : null}
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight text-ink inline-flex items-center gap-1.5 min-w-0">
                <span className="truncate">{title}</span>
                {user.official ? <OfficialMark kind="org" /> : null}
                {user.maintainer ? <MaintainerMark /> : null}
              </h1>
              <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-mute">
                <span>@{user.user_id}</span>
                {githubHref ? (
                  <a
                    href={githubHref}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex text-mute hover:text-ink"
                    aria-label={`${user.user_id} on GitHub`}
                  >
                    <GitHubIcon className="h-4 w-4" />
                  </a>
                ) : null}
              </p>
            </div>
          </div>
          <DescriptionEditor
            value={user.description || ""}
            canEdit={isSelf}
            maxLength={USER_DESCRIPTION_MAX}
            emptyLabel=""
            onSave={async (next) => {
              const updated = await updateUserDescription(
                user.user_id,
                next,
                token,
              );
              setUser(updated);
            }}
          />

          {user.official_orgs.length ? (
            <section className="space-y-2">
              <h2 className="text-sm font-medium text-ink">
                Official organizations
              </h2>
              <div className="blob-panel overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Organization</TableHead>
                      <TableHead>ID</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {user.official_orgs.map((org) => (
                      <TableRow key={org.org_id}>
                        <TableCell>
                          <Link
                            to={`/organizations/${encodeURIComponent(org.org_id)}`}
                            className={`inline-flex items-center gap-1.5 ${INTERNAL_LINK_CLASS}`}
                          >
                            <span>
                              {org.display_name || org.org_id}
                            </span>
                            <OfficialMark kind="org" />
                          </Link>
                        </TableCell>
                        <TableCell className="text-mute">
                          @{org.org_id}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </section>
          ) : null}

          <UserPackageSection
            title="Public datasets"
            empty="No public datasets uploaded by this account."
            rows={datasets}
            href={(row) => `/datasets/${encodeDatasetId(row.dataset_id)}`}
          />
          <UserPackageSection
            title="Public plugins"
            empty="No public plugins uploaded by this account."
            rows={plugins}
            href={(row) => `/plugins/${encodeDatasetId(row.dataset_id)}`}
            kind="plugin"
            onOpen={(id) => navigate(`/plugins/${encodeDatasetId(id)}`)}
          />
          <UserPackageSection
            title="Public agents"
            empty="No public agents uploaded by this account."
            rows={agents}
            href={(row) => `/agents/${encodeDatasetId(row.dataset_id)}`}
            kind="agent"
            onOpen={(id) => navigate(`/agents/${encodeDatasetId(id)}`)}
          />
        </div>
      ) : null}
    </>
  );
}

function UserPackageSection({
  title,
  empty,
  rows,
  href,
  kind = "dataset",
  onOpen,
}: {
  title: string;
  empty: string;
  rows: PackageRelease[];
  href: (row: PackageRelease) => string;
  kind?: "dataset" | "plugin" | "agent";
  onOpen?: (id: string) => void;
}) {
  const head =
    kind === "plugin" ? "Plugin" : kind === "agent" ? "Agent" : "Dataset";
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-ink">{title}</h2>
      {rows.length === 0 ? (
        <div className="rounded-[14px] border border-dashed border-hairline/70 p-6 text-sm text-mute">
          {empty}
        </div>
      ) : (kind === "plugin" || kind === "agent") && onOpen ? (
        <CatalogCardGrid kind={kind} rows={rows} onOpen={onOpen} />
      ) : (
        <div className="blob-panel overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>{head}</TableHead>
                <TableHead>Version</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.dataset_id}>
                  <TableCell>
                    <Link
                      to={href(row)}
                      className={`inline-flex min-w-0 items-center gap-1.5 text-sm ${INTERNAL_LINK_CLASS}`}
                    >
                      <span className="truncate">
                        {packageDisplayTitle(row.dataset_id, row.display_name)}
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell className="text-body">
                    {versionLabel(row)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
