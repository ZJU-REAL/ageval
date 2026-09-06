import { Building2, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState, LoadingState } from "@/components/empty-state";
import { HoverTip } from "@/components/hover-tip";
import { OfficialMark } from "@/components/official-mark";
import { PageHead } from "@/components/page-head";
import { SignInButton } from "@/components/sign-in-button";
import { Button } from "@/components/ui/button";
import { FloatingField } from "@/components/ui/floating-field";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  createOrg,
  joinOrgWithInvite,
  listOrgs,
  latestPackageByDataset,
  listPackages,
  type OrgRow,
  type PackageRelease,
  RegistryHttpError,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { sortRows, useTableSort } from "@/components/sortable-head";
import { TableColumnPicker } from "@/components/ui/table-column-picker";
import { useTableColumns } from "@/hooks/use-table-columns";
import { toastError } from "@/lib/toast-error";

const ORG_OPTIONAL_COLUMNS = [
  { id: "org_id", label: "ID" },
  { id: "datasets", label: "Datasets" },
  { id: "plugins", label: "Plugins" },
  { id: "agents", label: "Agents" },
] as const;
const ORG_OPTIONAL_IDS = ORG_OPTIONAL_COLUMNS.map((col) => col.id);
const ORG_OPTIONAL_DEFAULT: typeof ORG_OPTIONAL_IDS = [
  "datasets",
  "plugins",
  "agents",
];

export function OrganizationsPage() {
  const navigate = useNavigate();
  const token = getToken();
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [datasets, setDatasets] = useState<PackageRelease[]>([]);
  const [plugins, setPlugins] = useState<PackageRelease[]>([]);
  const [agents, setAgents] = useState<PackageRelease[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [columns, setColumns] = useTableColumns(
    "ageval.hub.columns.organizations",
    ORG_OPTIONAL_IDS,
    ORG_OPTIONAL_DEFAULT,
  );
  const sort = useTableSort();

  const [joinOpen, setJoinOpen] = useState(false);
  const [inviteKey, setInviteKey] = useState("");
  const [joinBusy, setJoinBusy] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [orgDisplayName, setOrgDisplayName] = useState("");
  const [orgDescription, setOrgDescription] = useState("");
  const [createBusy, setCreateBusy] = useState(false);

  const orgNameOk = /^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$/.test(
    orgName.trim().toLowerCase(),
  );

  function reload() {
    if (!token) return;
    setLoading(true);
    Promise.all([
      listOrgs(token),
      listPackages(token, { packageKind: "dataset" }),
      listPackages(token, { packageKind: "plugin" }),
      listPackages(token, { packageKind: "agent" }),
    ])
      .then(([orgRows, datasetRows, pluginRows, agentRows]) => {
        setOrgs(orgRows);
        setDatasets(datasetRows);
        setPlugins(pluginRows);
        setAgents(agentRows);
        setError(null);
      })
      .catch((err: unknown) => {
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setOrgs([]);
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!token) {
      setLoading(false);
      setOrgs([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([
      listOrgs(token),
      listPackages(token, { packageKind: "dataset" }),
      listPackages(token, { packageKind: "plugin" }),
      listPackages(token, { packageKind: "agent" }),
    ])
      .then(([orgRows, datasetRows, pluginRows, agentRows]) => {
        if (cancelled) return;
        setOrgs(orgRows);
        setDatasets(datasetRows);
        setPlugins(pluginRows);
        setAgents(agentRows);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setOrgs([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const datasetCountByOrg = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of latestPackageByDataset(datasets)) {
      if (!row.org_id) continue;
      counts.set(row.org_id, (counts.get(row.org_id) ?? 0) + 1);
    }
    return counts;
  }, [datasets]);

  const pluginCountByOrg = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of latestPackageByDataset(plugins)) {
      if (!row.org_id) continue;
      counts.set(row.org_id, (counts.get(row.org_id) ?? 0) + 1);
    }
    return counts;
  }, [plugins]);

  const agentCountByOrg = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of latestPackageByDataset(agents)) {
      if (!row.org_id) continue;
      counts.set(row.org_id, (counts.get(row.org_id) ?? 0) + 1);
    }
    return counts;
  }, [agents]);

  useEffect(() => {
    if (
      sort.sortKey === "org_id" ||
      sort.sortKey === "datasets" ||
      sort.sortKey === "plugins" ||
      sort.sortKey === "agents"
    ) {
      if (!columns.includes(sort.sortKey)) {
        sort.setSortKey(null);
        sort.setSortDir(null);
      }
    }
  }, [columns, sort.sortKey, sort.setSortKey, sort.setSortDir]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = !q
      ? orgs
      : orgs.filter(
          (o) =>
            o.org_id.toLowerCase().includes(q) ||
            (o.display_name || "").toLowerCase().includes(q) ||
            (o.name || "").toLowerCase().includes(q),
        );
    return sortRows(matched, sort.sortKey, sort.sortDir, (org, key) => {
      switch (key) {
        case "name":
          return org.display_name || org.name || org.org_id;
        case "org_id":
          return org.org_id;
        case "role":
          return org.role || "";
        case "datasets":
          return datasetCountByOrg.get(org.org_id) ?? 0;
        case "plugins":
          return pluginCountByOrg.get(org.org_id) ?? 0;
        case "agents":
          return agentCountByOrg.get(org.org_id) ?? 0;
        default:
          return null;
      }
    });
  }, [
    orgs,
    query,
    sort.sortKey,
    sort.sortDir,
    datasetCountByOrg,
    pluginCountByOrg,
    agentCountByOrg,
  ]);

  async function submitCreate() {
    if (!token) return;
    const name = orgName.trim().toLowerCase();
    if (!/^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$/.test(name)) {
      toastError("Slug must be lowercase [a-z0-9][a-z0-9_-]*");
      return;
    }
    setCreateBusy(true);
    try {
      const created = await createOrg(
        {
          name,
          display_name: orgDisplayName.trim() || name,
          description: orgDescription.trim(),
        },
        token,
      );
      setCreateOpen(false);
      setOrgName("");
      setOrgDisplayName("");
      setOrgDescription("");
      navigate(`/organizations/${encodeURIComponent(created.org_id || name)}`);
    } catch (err: unknown) {
      toastError(err);
    } finally {
      setCreateBusy(false);
    }
  }

  async function submitJoin() {
    if (!token) return;
    const key = inviteKey.trim();
    if (!key) {
      toastError("Invite key is required");
      return;
    }
    setJoinBusy(true);
    try {
      const joined = await joinOrgWithInvite(key, token);
      setJoinOpen(false);
      setInviteKey("");
      reload();
      if (joined.org_id) {
        navigate(`/organizations/${encodeURIComponent(joined.org_id)}`);
      }
    } catch (err: unknown) {
      toastError(err);
    } finally {
      setJoinBusy(false);
    }
  }

  return (
    <>
      <PageHead
        title="Organizations"
        sub="Organizations you belong to. Packages are published under an org."
      />

      {!token ? (
        <EmptyState
          icon={Building2}
          glyph="orgs"
          title="Sign in to see org packages"
          action={<SignInButton />}
        />
      ) : loading ? (
        <LoadingState label="Loading organizations" />
      ) : error ? (
        <div className="blob-panel p-4 text-sm">
          <p className="text-error font-medium">Could not load organizations</p>
          <p className="mt-1 text-xs text-body">{error}</p>
        </div>
      ) : (
        <>
          <div className="mb-3 flex w-full items-center gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search your organizations…"
              aria-label="Search organizations"
              className="flex-1 min-w-0 focus-visible:border-hairline"
            />
            <TableColumnPicker
              options={ORG_OPTIONAL_COLUMNS}
              value={columns}
              onChange={setColumns}
              ariaLabel="Optional organization columns"
            />
            <HoverTip content="Join with invite key">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="shrink-0"
              aria-label="Join organization with invite key"
              onClick={() => {
                setJoinOpen(true);
              }}
            >
              <Plus className="h-4 w-4" />
            </Button>
            </HoverTip>
            <Button
              type="button"
              size="sm"
              className="shrink-0"
              onClick={() => {
                setCreateOpen(true);
              }}
            >
              New org
            </Button>
          </div>
          {filtered.length === 0 ? (
            query.trim() ? (
              <EmptyState
                icon={Building2}
                glyph="orgs"
                title="No matches"
                action={
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setQuery("")}
                  >
                    Clear search
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon={Building2}
                glyph="orgs"
                title="No organizations"
                caption="Create one, or join with an invite key."
              />
            )
          ) : (
            <>
            <div className="blob-panel overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>{sort.head("name", "Organization")}</TableHead>
                    {columns.includes("org_id") ? (
                      <TableHead>{sort.head("org_id", "ID")}</TableHead>
                    ) : null}
                    <TableHead>{sort.head("role", "Role")}</TableHead>
                    {columns.includes("datasets") ? (
                      <TableHead className="tabular-nums">
                        {sort.head("datasets", "Datasets")}
                      </TableHead>
                    ) : null}
                    {columns.includes("plugins") ? (
                      <TableHead className="tabular-nums">
                        {sort.head("plugins", "Plugins")}
                      </TableHead>
                    ) : null}
                    {columns.includes("agents") ? (
                      <TableHead className="tabular-nums">
                        {sort.head("agents", "Agents")}
                      </TableHead>
                    ) : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((org) => (
                    <TableRow
                      key={org.org_id}
                      className="cursor-pointer"
                      onClick={() =>
                        navigate(
                          `/organizations/${encodeURIComponent(org.org_id)}`,
                        )
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          navigate(
                            `/organizations/${encodeURIComponent(org.org_id)}`,
                          );
                        }
                      }}
                      tabIndex={0}
                      role="link"
                    >
                      <TableCell className="font-medium text-ink">
                        <span className="inline-flex items-center gap-1.5 min-w-0">
                          <span className="truncate">
                            {org.display_name || org.name || org.org_id}
                          </span>
                          {org.official ? <OfficialMark kind="org" /> : null}
                        </span>
                      </TableCell>
                      {columns.includes("org_id") ? (
                        <TableCell className="text-mute">
                          @{org.org_id}
                        </TableCell>
                      ) : null}
                      <TableCell className="text-body capitalize">
                        {org.role || "—"}
                      </TableCell>
                      {columns.includes("datasets") ? (
                        <TableCell className="tabular-nums text-body">
                          {datasetCountByOrg.get(org.org_id) ?? 0}
                        </TableCell>
                      ) : null}
                      {columns.includes("plugins") ? (
                        <TableCell className="tabular-nums text-body">
                          {pluginCountByOrg.get(org.org_id) ?? 0}
                        </TableCell>
                      ) : null}
                      {columns.includes("agents") ? (
                        <TableCell className="tabular-nums text-body">
                          {agentCountByOrg.get(org.org_id) ?? 0}
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            </>
          )}
          <p className="text-xs text-mute mt-3 tabular-nums">
            {filtered.length} organization
            {filtered.length === 1 ? "" : "s"}
          </p>
        </>
      )}

      {createOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-org-title"
          onClick={(e) => {
            if (e.target === e.currentTarget && !createBusy) setCreateOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-[14px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)] p-5 space-y-4">
            <div>
              <h2
                id="create-org-title"
                className="text-lg font-semibold tracking-tight text-ink"
              >
                Create organization
              </h2>
              <p className="text-sm text-mute mt-1">
                You become the owner. Packages publish under this slug.
              </p>
            </div>
            <div>
              <label
                htmlFor="org-name-input"
                className="text-sm font-medium text-ink"
              >
                Slug
              </label>
              <Input
                id="org-name-input"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                placeholder="my-lab"
                className="mt-1.5 text-sm"
                autoFocus
                disabled={createBusy}
                maxLength={64}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submitCreate();
                }}
              />
              <p className="mt-1 text-xs text-mute">
                Lowercase letters, digits, hyphen, underscore.
              </p>
            </div>
            <div>
              <label
                htmlFor="org-display-input"
                className="text-sm font-medium text-ink"
              >
                Display name
              </label>
              <Input
                id="org-display-input"
                value={orgDisplayName}
                onChange={(e) => setOrgDisplayName(e.target.value)}
                placeholder="Optional — defaults to the slug"
                className="mt-1.5 text-sm"
                disabled={createBusy}
                maxLength={80}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submitCreate();
                }}
              />
            </div>
            <FloatingField
              multiline
              id="org-description-input"
              label="Description"
              value={orgDescription}
              onChange={(e) => setOrgDescription(e.target.value)}
              disabled={createBusy}
              maxLength={500}
            />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={createBusy}
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                disabled={createBusy || !orgNameOk}
                onClick={() => void submitCreate()}
              >
                {createBusy ? "Creating…" : "Create"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {joinOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="join-org-title"
          onClick={(e) => {
            if (e.target === e.currentTarget && !joinBusy) setJoinOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-[14px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)] p-5 space-y-4">
            <div>
              <h2
                id="join-org-title"
                className="text-lg font-semibold tracking-tight text-ink"
              >
                Join organization
              </h2>
              <p className="text-sm text-mute mt-1">
                Paste an invite key from an org owner. You will join as a member.
              </p>
            </div>
            <div>
              <label
                htmlFor="invite-key-input"
                className="text-sm font-medium text-ink"
              >
                Invite key
              </label>
              <Input
                id="invite-key-input"
                value={inviteKey}
                onChange={(e) => setInviteKey(e.target.value)}
                placeholder="ageval-inv_…"
                className="mt-1.5 text-sm"
                autoFocus
                disabled={joinBusy}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submitJoin();
                }}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={joinBusy}
                onClick={() => setJoinOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                disabled={joinBusy || !inviteKey.trim()}
                onClick={() => void submitJoin()}
              >
                {joinBusy ? "Joining…" : "Join"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
